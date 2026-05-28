from __future__ import annotations

from collections.abc import Generator
from importlib import import_module
from os import environ
from pathlib import Path

import pytest

from relay_teams.persistence import close_live_sqlite_repositories_async
from relay_teams.persistence.db import run_async_blocking
from relay_teams.secrets import AppSecretStore

_UNIT_TEST_KEYRING_BACKEND_ENV = "PYTHON_KEYRING_BACKEND"
_UNIT_TEST_KEYRING_BACKEND = "keyring.backends.null.Keyring"
environ.setdefault(_UNIT_TEST_KEYRING_BACKEND_ENV, _UNIT_TEST_KEYRING_BACKEND)

_UNIT_TESTS_ROOT = Path(__file__).resolve().parent
_DEFAULT_UNIT_TEST_TIMEOUT_SECONDS = 5.0
_UNIT_TEST_TIMEOUT_ENV = "RELAY_TEAMS_UNIT_TEST_TIMEOUT_SECONDS"
_KEYRING_MODULE_NAMES = (
    "relay_teams.agent_runtimes.secret_store",
    "relay_teams.env.clawhub_secret_store",
    "relay_teams.env.github_secret_store",
    "relay_teams.env.proxy_secret_store",
    "relay_teams.env.web_secret_store",
    "relay_teams.gateway.feishu.secret_store",
    "relay_teams.gateway.wechat.secret_store",
)
_UNIT_TEST_NOTIFICATION_HOOK_LOOP: object | None = None


class _UnitTestSecretStore(AppSecretStore):
    def has_usable_keyring_backend(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _disable_system_keyring_for_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    import relay_teams.secrets.secret_store as secret_store

    unit_secret_store = _UnitTestSecretStore()
    monkeypatch.setattr(secret_store, "_SECRET_STORE", unit_secret_store)
    monkeypatch.setattr(secret_store, "keyring", None)
    for module_name in _KEYRING_MODULE_NAMES:
        module = import_module(module_name)
        monkeypatch.setattr(module, "keyring", None)

    import relay_teams.env.proxy_secret_store as proxy_secret_store

    monkeypatch.setattr(
        proxy_secret_store,
        "_PROXY_SECRET_STORE",
        proxy_secret_store.ProxySecretStore(secret_store=unit_secret_store),
    )


@pytest.fixture(autouse=True)
def _disable_unit_test_background_pollers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import relay_teams.gateway.xiaoluban.service as xiaoluban_service
    import relay_teams.notifications.notification_service as notification_service

    def _mark_xiaoluban_poller_started(self: object) -> None:
        setattr(self, "_im_poller_started", True)

    def _shared_notification_hook_loop(self: object) -> object:
        _ = self
        global _UNIT_TEST_NOTIFICATION_HOOK_LOOP
        if _UNIT_TEST_NOTIFICATION_HOOK_LOOP is None:
            _UNIT_TEST_NOTIFICATION_HOOK_LOOP = (
                notification_service._NotificationHookLoop()
            )
        return _UNIT_TEST_NOTIFICATION_HOOK_LOOP

    monkeypatch.setattr(
        xiaoluban_service.XiaolubanGatewayService,
        "_ensure_poller_started",
        _mark_xiaoluban_poller_started,
    )
    monkeypatch.setattr(
        notification_service.NotificationService,
        "_get_hook_loop",
        _shared_notification_hook_loop,
    )


@pytest.fixture(autouse=True)
def _close_sqlite_repositories_after_unit_test() -> Generator[None, None, None]:
    yield
    run_async_blocking(close_live_sqlite_repositories_async())


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.pluginmanager.hasplugin("timeout"):
        raise pytest.UsageError(
            "pytest-timeout is required for unit-test timeout enforcement"
        )
    timeout_marker = pytest.mark.timeout(_unit_test_timeout_seconds())
    for item in items:
        item_path = Path(str(item.fspath)).resolve()
        if _UNIT_TESTS_ROOT not in item_path.parents:
            continue
        if item.get_closest_marker("timeout") is not None:
            continue
        item.add_marker(timeout_marker)


def _unit_test_timeout_seconds() -> float:
    raw_timeout = environ.get(_UNIT_TEST_TIMEOUT_ENV)
    if raw_timeout is None:
        return _DEFAULT_UNIT_TEST_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise pytest.UsageError(
            f"{_UNIT_TEST_TIMEOUT_ENV} must be a positive number"
        ) from exc
    if timeout_seconds <= 0:
        raise pytest.UsageError(f"{_UNIT_TEST_TIMEOUT_ENV} must be a positive number")
    return timeout_seconds
