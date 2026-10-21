"""Execute the prepared Graphify command without deciding file conformity."""

import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from tools.install_sandbox.contracts.case import install_arguments
from tools.install_sandbox.contracts.case_transport import ExecutionCase, load_case
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
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
    environment: dict[str, str] | None = None


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
        self,
        case: ExecutionCase,
        executable: Path,
        project: Path,
        home: Path,
        temporary: Path,
        resolution: Path | None = None,
    ) -> InstallerCommandResult:
        case = load_case(case.to_json())
        native = isinstance(case, EffectInstallCase)
        arguments = list(case.subject.invocation) if native else install_arguments(case)
        args = [str(executable), *arguments]
        if resolution is not None and (native or case.spec.json_hook_management != "registry"):
            raise ValueError("Undeclared managed resolution")
        if resolution is not None:
            args.extend(["--managed-hooks-resolution", str(resolution)])
        environment = command_environment(home, temporary)
        if native or case.spec.command is not None:
            environment.update(isolated_configuration(home, temporary))
        result = self.execute(args, project, environment, self.timeout)
        return replace(result, environment=environment)


def isolated_configuration(home: Path, temporary: Path) -> dict[str, str]:
    """Declare local configuration roots for dedicated installation commands."""
    names = (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "APPDATA",
        "LOCALAPPDATA",
    )
    return {
        **{name: str(temporary / "configuration" / name.lower()) for name in names},
        "USERPROFILE": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
