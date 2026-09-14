"""Execute the prepared Graphify command without deciding file conformity."""

import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.timings import elapsed


@dataclass(frozen=True)
class InstallerCommandResult:
    args: list[str]
    cwd: str
    state: Literal["completed", "not_started", "interrupted"]
    exit_code: int | None
    reason: str | None
    stdout: bytes = b""
    stderr: bytes = b""
    duration_seconds: float | None = None


CommandExecutor = Callable[[list[str], Path, dict[str, str], float], InstallerCommandResult]


def _collect(process: subprocess.Popen[bytes], timeout: float) -> tuple[bytes, bytes, str | None]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        reason = f"Terminated by signal {-process.returncode}" if process.returncode < 0 else None
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        reason = (
            "Command interrupted" if isinstance(error, KeyboardInterrupt) else "Command timed out"
        )
        # Stop the whole command group before observing its remaining file effects.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    if reason:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    return stdout, stderr, reason


def execute_command(
    args: list[str], cwd: Path, environment: dict[str, str], timeout: float
) -> InstallerCommandResult:
    if timeout <= 0:
        raise ValueError("Command timeout must be positive")
    started = time.monotonic_ns()
    try:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        return InstallerCommandResult(
            args, str(cwd), "not_started", None, str(error), duration_seconds=elapsed(started)
        )
    stdout, stderr, reason = _collect(process, timeout)
    state = "interrupted" if reason else "completed"
    return InstallerCommandResult(
        args, str(cwd), state, process.returncode, reason, stdout, stderr, elapsed(started)
    )


def command_environment(home: Path, temporary: Path) -> dict[str, str]:
    """Keep caller Python, user configuration and cache overrides out of the command."""
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
    }


class InstallerDriver:
    def __init__(self, execute: CommandExecutor = execute_command, *, timeout: float = 60):
        if timeout <= 0:
            raise ValueError("Command timeout must be positive")
        self.execute = execute
        self.timeout = timeout

    def install(
        self, case: InstallTestCase, executable: Path, project: Path, home: Path, temporary: Path
    ) -> InstallerCommandResult:
        InstallTestCase.from_json(case.to_json())
        args = [str(executable), "install", "--platform", case.target, "--project"]
        return self.execute(args, project, command_environment(home, temporary), self.timeout)
