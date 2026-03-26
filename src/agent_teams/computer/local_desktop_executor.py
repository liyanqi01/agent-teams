# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import binascii
import ctypes
from ctypes import wintypes
import platform
import struct
import time
from collections.abc import Sequence
from typing import Protocol, final
from uuid import uuid4
import zlib

from agent_teams.computer.action_models import (
    ComputerAction,
    ComputerActionClick,
    ComputerActionDoubleClick,
    ComputerActionDrag,
    ComputerActionKeypress,
    ComputerActionResult,
    ComputerActionScreenshot,
    ComputerActionScroll,
    ComputerActionType,
    ComputerActionWait,
    ComputerContext,
    ComputerPoint,
    ComputerScreenshot,
    MouseButton,
)
from agent_teams.computer.executor_contracts import ComputerExecutor


class _LocalDesktopDriver(Protocol):
    def start_session(self, *, run_id: str, instance_id: str) -> str: ...

    def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult: ...

    def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot: ...

    def get_context(self, *, session_id: str) -> ComputerContext: ...

    def stop_session(self, *, session_id: str) -> None: ...


@final
class LocalDesktopExecutor(ComputerExecutor):
    def __init__(self, *, driver: _LocalDesktopDriver | None = None) -> None:
        self._driver = driver or _build_local_desktop_driver()

    async def start_session(self, *, run_id: str, instance_id: str) -> str:
        return await asyncio.to_thread(
            self._driver.start_session,
            run_id=run_id,
            instance_id=instance_id,
        )

    async def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        return await asyncio.to_thread(
            self._driver.execute_action,
            session_id=session_id,
            action=action,
        )

    async def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        return await asyncio.to_thread(
            self._driver.capture_screenshot,
            session_id=session_id,
        )

    async def get_context(self, *, session_id: str) -> ComputerContext:
        return await asyncio.to_thread(
            self._driver.get_context,
            session_id=session_id,
        )

    async def stop_session(self, *, session_id: str) -> None:
        await asyncio.to_thread(self._driver.stop_session, session_id=session_id)


class _WindowsBitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _WindowsRgbQuad(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", wintypes.BYTE),
        ("rgbGreen", wintypes.BYTE),
        ("rgbRed", wintypes.BYTE),
        ("rgbReserved", wintypes.BYTE),
    ]


class _WindowsBitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _WindowsBitmapInfoHeader),
        ("bmiColors", _WindowsRgbQuad * 1),
    ]


ULONG_PTR = wintypes.WPARAM


class _WindowsMouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _WindowsKeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _WindowsHardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _WindowsInputUnion(ctypes.Union):
    _fields_ = [
        ("mi", _WindowsMouseInput),
        ("ki", _WindowsKeyboardInput),
        ("hi", _WindowsHardwareInput),
    ]


class _WindowsInput(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _WindowsInputUnion),
    ]


class _ResolvedKey:
    def __init__(self, *, vk: int, modifiers: tuple[int, ...]) -> None:
        self.vk = vk
        self.modifiers = modifiers


class _WindowsDesktopDriver:
    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040
    _MOUSEEVENTF_WHEEL = 0x0800
    _MOUSEEVENTF_HWHEEL = 0x01000
    _SRCCOPY = 0x00CC0020
    _BI_RGB = 0
    _DIB_RGB_COLORS = 0
    _SM_CXSCREEN = 0
    _SM_CYSCREEN = 1
    _WHEEL_DELTA = 120
    _WM_CHAR = 0x0102
    _VK_SHIFT = 0x10
    _VK_CONTROL = 0x11
    _VK_MENU = 0x12
    _VK_LWIN = 0x5B

    _NAMED_KEYS: dict[str, int] = {
        "alt": _VK_MENU,
        "backspace": 0x08,
        "capslock": 0x14,
        "command": _VK_LWIN,
        "ctrl": _VK_CONTROL,
        "delete": 0x2E,
        "down": 0x28,
        "end": 0x23,
        "enter": 0x0D,
        "esc": 0x1B,
        "escape": 0x1B,
        "home": 0x24,
        "left": 0x25,
        "meta": _VK_LWIN,
        "option": _VK_MENU,
        "pagedown": 0x22,
        "pageup": 0x21,
        "pgdn": 0x22,
        "pgup": 0x21,
        "return": 0x0D,
        "right": 0x27,
        "shift": _VK_SHIFT,
        "space": 0x20,
        "super": _VK_LWIN,
        "tab": 0x09,
        "up": 0x26,
        "win": _VK_LWIN,
        "windows": _VK_LWIN,
    }

    def __init__(self) -> None:
        self._sessions: set[str] = set()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._configure_apis()
        self._register_function_keys()

    def start_session(self, *, run_id: str, instance_id: str) -> str:
        _ = run_id
        _ = instance_id
        session_id = f"local-desktop-{uuid4()}"
        self._sessions.add(session_id)
        return session_id

    def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        self._require_session(session_id)
        if isinstance(action, ComputerActionClick):
            self._click(action.x, action.y, action.button)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="clicked",
            )
        if isinstance(action, ComputerActionDoubleClick):
            self._double_click(action.x, action.y, action.button)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="double-clicked",
            )
        if isinstance(action, ComputerActionDrag):
            self._drag(action.path)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="dragged",
            )
        if isinstance(action, ComputerActionScroll):
            self._scroll(action)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="scrolled",
            )
        if isinstance(action, ComputerActionKeypress):
            self._keypress(action.keys)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="pressed",
            )
        if isinstance(action, ComputerActionType):
            self._type_text(action.text)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="typed",
            )
        if isinstance(action, ComputerActionWait):
            time.sleep(action.seconds if action.seconds is not None else 0.5)
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="waited",
            )
        if isinstance(action, ComputerActionScreenshot):
            return ComputerActionResult(
                ok=True,
                action_type=action.type,
                message="captured",
            )
        raise RuntimeError(f"Unsupported computer action type: {action.type}")

    def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        self._require_session(session_id)
        width = self._user32.GetSystemMetrics(self._SM_CXSCREEN)
        height = self._user32.GetSystemMetrics(self._SM_CYSCREEN)
        desktop_window = self._user32.GetDesktopWindow()
        desktop_dc = self._user32.GetWindowDC(desktop_window)
        if desktop_dc == 0:
            raise RuntimeError("Failed to get desktop device context.")
        memory_dc = self._gdi32.CreateCompatibleDC(desktop_dc)
        if memory_dc == 0:
            self._user32.ReleaseDC(desktop_window, desktop_dc)
            raise RuntimeError("Failed to create compatible device context.")
        bitmap = self._gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
        if bitmap == 0:
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(desktop_window, desktop_dc)
            raise RuntimeError("Failed to create compatible bitmap.")
        previous = self._gdi32.SelectObject(memory_dc, bitmap)
        if previous == 0:
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(desktop_window, desktop_dc)
            raise RuntimeError("Failed to select bitmap into memory device context.")
        try:
            copied = self._gdi32.BitBlt(
                memory_dc,
                0,
                0,
                width,
                height,
                desktop_dc,
                0,
                0,
                self._SRCCOPY,
            )
            if copied == 0:
                raise RuntimeError("Failed to copy desktop bitmap.")
            bitmap_info = _WindowsBitmapInfo()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(_WindowsBitmapInfoHeader)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = self._BI_RGB
            buffer = ctypes.create_string_buffer(width * height * 4)
            scan_lines = self._gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(bitmap_info),
                self._DIB_RGB_COLORS,
            )
            if scan_lines == 0:
                raise RuntimeError("Failed to extract bitmap pixels.")
            png_bytes = self._encode_png(
                width=width,
                height=height,
                bgra_bytes=buffer.raw,
            )
            image_base64 = base64.b64encode(png_bytes).decode("ascii")
            return ComputerScreenshot(
                image_base64=image_base64,
                mime_type="image/png",
                width=width,
                height=height,
            )
        finally:
            self._gdi32.SelectObject(memory_dc, previous)
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(desktop_window, desktop_dc)

    def get_context(self, *, session_id: str) -> ComputerContext:
        self._require_session(session_id)
        return ComputerContext(
            screen_width=self._user32.GetSystemMetrics(self._SM_CXSCREEN),
            screen_height=self._user32.GetSystemMetrics(self._SM_CYSCREEN),
            current_url=None,
            active_window_title=self._active_window_title(),
        )

    def stop_session(self, *, session_id: str) -> None:
        self._sessions.discard(session_id)

    def _configure_apis(self) -> None:
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_WindowsInput),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            ULONG_PTR,
        ]
        self._user32.keybd_event.restype = None
        self._user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.SendMessageW.restype = ctypes.c_ssize_t
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int
        self._user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        self._user32.VkKeyScanW.restype = ctypes.c_short
        self._user32.GetDesktopWindow.argtypes = []
        self._user32.GetDesktopWindow.restype = wintypes.HWND
        self._user32.GetWindowDC.argtypes = [wintypes.HWND]
        self._user32.GetWindowDC.restype = wintypes.HDC
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.ReleaseDC.restype = ctypes.c_int

        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.DeleteDC.restype = wintypes.BOOL
        self._gdi32.CreateCompatibleBitmap.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self._gdi32.BitBlt.restype = wintypes.BOOL
        self._gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsBitmapInfo),
            wintypes.UINT,
        ]
        self._gdi32.GetDIBits.restype = ctypes.c_int

    def _register_function_keys(self) -> None:
        for index in range(1, 25):
            self._NAMED_KEYS[f"f{index}"] = 0x6F + index

    def _require_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise RuntimeError(f"Unknown local desktop session: {session_id}")

    def _click(self, x: int, y: int, button: MouseButton) -> None:
        self._move_cursor(x, y)
        down_flag, up_flag = self._mouse_flags(button)
        self._send_mouse_input(down_flag, 0)
        self._send_mouse_input(up_flag, 0)

    def _double_click(self, x: int, y: int, button: MouseButton) -> None:
        self._click(x, y, button)
        time.sleep(0.05)
        self._click(x, y, button)

    def _drag(self, path: Sequence[ComputerPoint]) -> None:
        first = path[0]
        self._move_cursor(first.x, first.y)
        self._send_mouse_input(self._MOUSEEVENTF_LEFTDOWN, 0)
        try:
            for point in path[1:]:
                self._move_cursor(point.x, point.y)
                time.sleep(0.02)
        finally:
            self._send_mouse_input(self._MOUSEEVENTF_LEFTUP, 0)

    def _scroll(self, action: ComputerActionScroll) -> None:
        self._move_cursor(action.x, action.y)
        if action.scroll_y != 0:
            self._send_mouse_input(
                self._MOUSEEVENTF_WHEEL,
                action.scroll_y * self._WHEEL_DELTA,
            )
        if action.scroll_x != 0:
            self._send_mouse_input(
                self._MOUSEEVENTF_HWHEEL,
                action.scroll_x * self._WHEEL_DELTA,
            )

    def _keypress(self, keys: Sequence[str]) -> None:
        resolved = [self._resolve_key(key) for key in keys]
        modifiers_pressed: list[int] = []
        try:
            for resolved_key in resolved[:-1]:
                self._send_key_input(resolved_key.vk, key_up=False)
                modifiers_pressed.append(resolved_key.vk)
            final_key = resolved[-1]
            for modifier_vk in final_key.modifiers:
                self._send_key_input(modifier_vk, key_up=False)
                modifiers_pressed.append(modifier_vk)
            self._send_key_input(final_key.vk, key_up=False)
            self._send_key_input(final_key.vk, key_up=True)
        finally:
            for vk in reversed(modifiers_pressed):
                self._send_key_input(vk, key_up=True)

    def _type_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                self._send_key_input(0x0D, key_up=False)
                self._send_key_input(0x0D, key_up=True)
                continue
            if char == "\t":
                self._send_key_input(0x09, key_up=False)
                self._send_key_input(0x09, key_up=True)
                continue
            try:
                resolved = self._resolve_printable_key(char)
            except RuntimeError:
                self._type_unicode_char(char)
                continue
            pressed_modifiers: list[int] = []
            try:
                for modifier_vk in resolved.modifiers:
                    self._send_key_input(modifier_vk, key_up=False)
                    pressed_modifiers.append(modifier_vk)
                self._send_key_input(resolved.vk, key_up=False)
                self._send_key_input(resolved.vk, key_up=True)
            finally:
                for modifier_vk in reversed(pressed_modifiers):
                    self._send_key_input(modifier_vk, key_up=True)

    def _type_unicode_char(self, char: str) -> None:
        handle = self._user32.GetForegroundWindow()
        if handle == 0:
            raise RuntimeError("Failed to find foreground window for unicode typing.")
        self._user32.SendMessageW(handle, self._WM_CHAR, ord(char), 0)

    def _move_cursor(self, x: int, y: int) -> None:
        moved = self._user32.SetCursorPos(x, y)
        if moved == 0:
            raise RuntimeError("Failed to move cursor.")

    def _mouse_flags(self, button: MouseButton) -> tuple[int, int]:
        if button == MouseButton.RIGHT:
            return self._MOUSEEVENTF_RIGHTDOWN, self._MOUSEEVENTF_RIGHTUP
        if button == MouseButton.MIDDLE:
            return self._MOUSEEVENTF_MIDDLEDOWN, self._MOUSEEVENTF_MIDDLEUP
        return self._MOUSEEVENTF_LEFTDOWN, self._MOUSEEVENTF_LEFTUP

    def _send_mouse_input(self, flags: int, mouse_data: int) -> None:
        self._send_inputs(
            [
                _WindowsInput(
                    type=self._INPUT_MOUSE,
                    mi=_WindowsMouseInput(
                        dx=0,
                        dy=0,
                        mouseData=mouse_data,
                        dwFlags=flags,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            ]
        )

    def _send_key_input(self, vk: int, *, key_up: bool) -> None:
        flags = self._KEYEVENTF_KEYUP if key_up else 0
        self._user32.keybd_event(vk, 0, flags, 0)

    def _keyboard_input(
        self,
        vk: int,
        scan_code: int,
        key_up: bool,
        *,
        unicode_input: bool = False,
    ) -> _WindowsInput:
        flags = 0
        if key_up:
            flags |= self._KEYEVENTF_KEYUP
        if unicode_input:
            flags |= self._KEYEVENTF_UNICODE
        return _WindowsInput(
            type=self._INPUT_KEYBOARD,
            ki=_WindowsKeyboardInput(
                wVk=vk,
                wScan=scan_code,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    def _send_inputs(self, inputs: Sequence[_WindowsInput]) -> None:
        if not inputs:
            return
        array_type = _WindowsInput * len(inputs)
        sent = self._user32.SendInput(
            len(inputs),
            array_type(*inputs),
            ctypes.sizeof(_WindowsInput),
        )
        if sent != len(inputs):
            raise RuntimeError("Failed to send desktop input.")

    def _resolve_key(self, key: str) -> _ResolvedKey:
        normalized = key.strip().lower()
        if not normalized:
            raise RuntimeError("Keyboard shortcut contains an empty key token.")
        direct = self._NAMED_KEYS.get(normalized)
        if direct is not None:
            return _ResolvedKey(vk=direct, modifiers=())
        if len(key) == 1:
            return self._resolve_printable_key(key)
        raise RuntimeError(f"Unsupported keyboard key: {key}")

    def _resolve_printable_key(self, key: str) -> _ResolvedKey:
        if key.isascii() and key.isalpha():
            return _ResolvedKey(vk=ord(key.upper()), modifiers=())
        if key.isascii() and key.isdigit():
            return _ResolvedKey(vk=ord(key), modifiers=())
        translated = int(self._user32.VkKeyScanW(key))
        if translated == -1:
            raise RuntimeError(f"Unsupported keyboard key: {key}")
        vk = translated & 0xFF
        modifier_mask = (translated >> 8) & 0xFF
        modifiers: list[int] = []
        if modifier_mask & 1:
            modifiers.append(self._VK_SHIFT)
        if modifier_mask & 2:
            modifiers.append(self._VK_CONTROL)
        if modifier_mask & 4:
            modifiers.append(self._VK_MENU)
        return _ResolvedKey(vk=vk, modifiers=tuple(modifiers))

    def _active_window_title(self) -> str | None:
        handle = self._user32.GetForegroundWindow()
        if handle == 0:
            return None
        length = self._user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = self._user32.GetWindowTextW(handle, buffer, len(buffer))
        if copied <= 0:
            return None
        title = buffer.value.strip()
        return title or None

    def _encode_png(self, *, width: int, height: int, bgra_bytes: bytes) -> bytes:
        row_stride = width * 4
        raw = bytearray()
        for row_start in range(0, len(bgra_bytes), row_stride):
            raw.append(0)
            row = bgra_bytes[row_start : row_start + row_stride]
            for offset in range(0, len(row), 4):
                blue = row[offset]
                green = row[offset + 1]
                red = row[offset + 2]
                alpha = row[offset + 3]
                raw.extend((red, green, blue, alpha))
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        idat = zlib.compress(bytes(raw), level=6)
        return b"".join(
            (
                b"\x89PNG\r\n\x1a\n",
                self._png_chunk(b"IHDR", ihdr),
                self._png_chunk(b"IDAT", idat),
                self._png_chunk(b"IEND", b""),
            )
        )

    def _png_chunk(self, chunk_type: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(chunk_type)
        crc = binascii.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _build_local_desktop_driver() -> _LocalDesktopDriver:
    if platform.system() != "Windows":
        raise RuntimeError(
            "local_desktop computer executor currently supports Windows only."
        )
    return _WindowsDesktopDriver()
