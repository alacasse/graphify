from __future__ import annotations

import os
import sys
from collections.abc import Callable
from contextlib import suppress

import pytest

from tools.install_sandbox.sandbox_runtime import supervisor


def _invoke_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    invoke: Callable[[], object],
) -> bytes:
    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("GRAPHIFY_SANDBOX_SUPERVISOR_STATUS_FD", str(write_fd))
    monkeypatch.setattr(sys, "argv", ("supervisor", *argv))
    try:
        invoke()
    finally:
        with suppress(OSError):
            os.close(write_fd)
    try:
        return os.read(read_fd, 8192)
    finally:
        os.close(read_fd)


def test_supervisor_main_reports_process_custody_and_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invoke() -> None:
        with pytest.raises(SystemExit) as raised:
            supervisor.main()
        assert raised.value.code == 7

    status = _invoke_supervisor(
        monkeypatch,
        (sys.executable, "-c", "raise SystemExit(7)"),
        invoke,
    )

    assert status == b"SPAWNEDTARGET_EXIT:7QUIESCENT"


def test_supervisor_main_rejects_missing_command_and_spawn_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_status = _invoke_supervisor(
        monkeypatch,
        (),
        lambda: _assert_return(supervisor.main(), 125),
    )
    spawn_status = _invoke_supervisor(
        monkeypatch,
        ("/graphify-fixture/missing-command",),
        lambda: _assert_return(supervisor.main(), 127),
    )

    assert empty_status == b"SPAWN_ERROR:command argv is empty"
    assert spawn_status.startswith(b"SPAWN_ERROR:")


def test_supervisor_main_requires_its_private_status_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAPHIFY_SANDBOX_SUPERVISOR_STATUS_FD", raising=False)
    monkeypatch.setattr(sys, "argv", ("supervisor", sys.executable))

    assert supervisor.main() == 125


def _assert_return(actual: object, expected: object) -> None:
    assert actual == expected
