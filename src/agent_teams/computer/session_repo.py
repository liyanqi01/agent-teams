# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from agent_teams.computer.action_models import (
    ComputerSessionRecord,
    ComputerSessionStatus,
    ComputerTurnRecord,
    ComputerTurnStatus,
)
from agent_teams.persistence.db import open_sqlite, run_sqlite_write_with_retry


class ComputerSessionRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._conn = open_sqlite(db_path)
        self._conn.row_factory = sqlite3.Row
        self._lock = RLock()
        self._init_tables()

    def _init_tables(self) -> None:
        def operation() -> None:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS computer_sessions (
                    computer_session_id TEXT PRIMARY KEY,
                    session_id          TEXT NOT NULL,
                    run_id              TEXT NOT NULL,
                    task_id             TEXT NOT NULL,
                    instance_id         TEXT NOT NULL,
                    role_id             TEXT NOT NULL,
                    status              TEXT NOT NULL,
                    current_url         TEXT,
                    active_window_title TEXT,
                    last_error          TEXT,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    completed_at        TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS computer_turns (
                    turn_id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    computer_session_id    TEXT NOT NULL,
                    session_id             TEXT NOT NULL,
                    run_id                 TEXT NOT NULL,
                    task_id                TEXT NOT NULL,
                    instance_id            TEXT NOT NULL,
                    role_id                TEXT NOT NULL,
                    step_index             INTEGER NOT NULL,
                    response_id            TEXT,
                    tool_call_id           TEXT,
                    action_type            TEXT NOT NULL,
                    action_json            TEXT NOT NULL,
                    result_json            TEXT NOT NULL DEFAULT '{}',
                    screenshot_artifact_path TEXT,
                    current_url            TEXT,
                    active_window_title    TEXT,
                    status                 TEXT NOT NULL,
                    error_message          TEXT,
                    created_at             TEXT NOT NULL,
                    FOREIGN KEY(computer_session_id) REFERENCES computer_sessions(computer_session_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_computer_turns_session_step
                ON computer_turns(computer_session_id, step_index)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_computer_sessions_session_updated
                ON computer_sessions(session_id, updated_at DESC)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_computer_sessions_run_updated
                ON computer_sessions(run_id, updated_at DESC)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_computer_turns_run_step
                ON computer_turns(run_id, step_index ASC)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_computer_turns_session_step_lookup
                ON computer_turns(session_id, step_index ASC)
                """
            )

        run_sqlite_write_with_retry(
            conn=self._conn,
            db_path=self._db_path,
            operation=operation,
            lock=self._lock,
            repository_name="ComputerSessionRepository",
            operation_name="init_tables",
        )

    def upsert_session(self, record: ComputerSessionRecord) -> ComputerSessionRecord:
        def operation() -> None:
            existing = self.get_session(record.computer_session_id)
            created_at = (
                existing.created_at.isoformat()
                if existing is not None
                else record.created_at.isoformat()
            )
            self._conn.execute(
                """
                INSERT INTO computer_sessions(
                    computer_session_id,
                    session_id,
                    run_id,
                    task_id,
                    instance_id,
                    role_id,
                    status,
                    current_url,
                    active_window_title,
                    last_error,
                    created_at,
                    updated_at,
                    completed_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(computer_session_id)
                DO UPDATE SET
                    session_id=excluded.session_id,
                    run_id=excluded.run_id,
                    task_id=excluded.task_id,
                    instance_id=excluded.instance_id,
                    role_id=excluded.role_id,
                    status=excluded.status,
                    current_url=excluded.current_url,
                    active_window_title=excluded.active_window_title,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at
                """,
                (
                    record.computer_session_id,
                    record.session_id,
                    record.run_id,
                    record.task_id,
                    record.instance_id,
                    record.role_id,
                    record.status.value,
                    record.current_url,
                    record.active_window_title,
                    record.last_error,
                    created_at,
                    record.updated_at.isoformat(),
                    record.completed_at.isoformat()
                    if record.completed_at is not None
                    else None,
                ),
            )

        run_sqlite_write_with_retry(
            conn=self._conn,
            db_path=self._db_path,
            operation=operation,
            lock=self._lock,
            repository_name="ComputerSessionRepository",
            operation_name="upsert_session",
        )
        persisted = self.get_session(record.computer_session_id)
        if persisted is None:
            raise RuntimeError(
                f"Failed to persist computer session {record.computer_session_id}"
            )
        return persisted

    def record_turn(self, record: ComputerTurnRecord) -> ComputerTurnRecord:
        def operation() -> None:
            self._conn.execute(
                """
                INSERT INTO computer_turns(
                    computer_session_id,
                    session_id,
                    run_id,
                    task_id,
                    instance_id,
                    role_id,
                    step_index,
                    response_id,
                    tool_call_id,
                    action_type,
                    action_json,
                    result_json,
                    screenshot_artifact_path,
                    current_url,
                    active_window_title,
                    status,
                    error_message,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.computer_session_id,
                    record.session_id,
                    record.run_id,
                    record.task_id,
                    record.instance_id,
                    record.role_id,
                    record.step_index,
                    record.response_id,
                    record.tool_call_id,
                    record.action_type,
                    record.action_json,
                    record.result_json,
                    record.screenshot_artifact_path,
                    record.current_url,
                    record.active_window_title,
                    record.status.value,
                    record.error_message,
                    record.created_at.isoformat(),
                ),
            )

        run_sqlite_write_with_retry(
            conn=self._conn,
            db_path=self._db_path,
            operation=operation,
            lock=self._lock,
            repository_name="ComputerSessionRepository",
            operation_name="record_turn",
        )
        stored = self.get_turn(
            computer_session_id=record.computer_session_id,
            step_index=record.step_index,
        )
        if stored is None:
            raise RuntimeError(
                "Failed to persist computer turn "
                f"{record.computer_session_id}:{record.step_index}"
            )
        return stored

    def get_session(self, computer_session_id: str) -> ComputerSessionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM computer_sessions WHERE computer_session_id=?",
                (computer_session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._to_session_record(row)

    def get_turn(
        self,
        *,
        computer_session_id: str,
        step_index: int,
    ) -> ComputerTurnRecord | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM computer_turns
                WHERE computer_session_id=? AND step_index=?
                """,
                (computer_session_id, step_index),
            ).fetchone()
        if row is None:
            return None
        return self._to_turn_record(row)

    def list_turns(self, computer_session_id: str) -> tuple[ComputerTurnRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM computer_turns
                WHERE computer_session_id=?
                ORDER BY step_index ASC, turn_id ASC
                """,
                (computer_session_id,),
            ).fetchall()
        return tuple(self._to_turn_record(row) for row in rows)

    def list_sessions_by_run(self, run_id: str) -> tuple[ComputerSessionRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM computer_sessions
                WHERE run_id=?
                ORDER BY updated_at DESC
                """,
                (run_id,),
            ).fetchall()
        return tuple(self._to_session_record(row) for row in rows)

    def delete_by_session(self, session_id: str) -> None:
        def operation() -> None:
            self._conn.execute(
                "DELETE FROM computer_turns WHERE session_id=?",
                (session_id,),
            )
            self._conn.execute(
                "DELETE FROM computer_sessions WHERE session_id=?",
                (session_id,),
            )

        run_sqlite_write_with_retry(
            conn=self._conn,
            db_path=self._db_path,
            operation=operation,
            lock=self._lock,
            repository_name="ComputerSessionRepository",
            operation_name="delete_by_session",
        )

    def _to_session_record(self, row: sqlite3.Row) -> ComputerSessionRecord:
        completed_at_raw = row["completed_at"]
        return ComputerSessionRecord(
            computer_session_id=str(row["computer_session_id"]),
            session_id=str(row["session_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            instance_id=str(row["instance_id"]),
            role_id=str(row["role_id"]),
            status=ComputerSessionStatus(str(row["status"])),
            current_url=str(row["current_url"]) if row["current_url"] else None,
            active_window_title=(
                str(row["active_window_title"]) if row["active_window_title"] else None
            ),
            last_error=str(row["last_error"]) if row["last_error"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            completed_at=(
                datetime.fromisoformat(str(completed_at_raw))
                if completed_at_raw
                else None
            ),
        )

    def _to_turn_record(self, row: sqlite3.Row) -> ComputerTurnRecord:
        turn_id_raw = row["turn_id"]
        return ComputerTurnRecord(
            turn_id=int(turn_id_raw) if turn_id_raw is not None else None,
            computer_session_id=str(row["computer_session_id"]),
            session_id=str(row["session_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            instance_id=str(row["instance_id"]),
            role_id=str(row["role_id"]),
            step_index=int(row["step_index"]),
            response_id=str(row["response_id"]) if row["response_id"] else None,
            tool_call_id=str(row["tool_call_id"]) if row["tool_call_id"] else None,
            action_type=str(row["action_type"]),
            action_json=str(row["action_json"]),
            result_json=str(row["result_json"]),
            screenshot_artifact_path=(
                str(row["screenshot_artifact_path"])
                if row["screenshot_artifact_path"]
                else None
            ),
            current_url=str(row["current_url"]) if row["current_url"] else None,
            active_window_title=(
                str(row["active_window_title"]) if row["active_window_title"] else None
            ),
            status=ComputerTurnStatus(str(row["status"])),
            error_message=str(row["error_message"]) if row["error_message"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
