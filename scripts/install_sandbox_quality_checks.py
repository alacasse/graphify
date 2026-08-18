"""Construction and execution of independent install-sandbox fast checks."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYRIGHT_CONFIG,
    security_configuration_error,
    typing_configuration_error,
)

CONFIGURATION_EXIT = 2
RUFF_CONFIG = "ruff.install-sandbox.toml"
ConfigurationCheck = Callable[[Path], str | None]


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    configuration_check: ConfigurationCheck | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class FastCheckRun:
    results: tuple[CheckResult, ...]
    configuration_error: str | None = None


FAST_CHECKS = (
    Check(
        name="ruff-format",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "ruff",
            "format",
            "--config",
            RUFF_CONFIG,
            "--check",
            INSTALL_SANDBOX,
        ),
    ),
    Check(
        name="ruff-lint",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "ruff",
            "check",
            "--config",
            RUFF_CONFIG,
            INSTALL_SANDBOX,
        ),
    ),
    Check(
        name="pyright",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "pyright",
            "--project",
            PYRIGHT_CONFIG,
            "--warnings",
        ),
        configuration_check=typing_configuration_error,
    ),
    Check(
        name="bandit",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "bandit",
            "-r",
            INSTALL_SANDBOX,
            "-ll",
            "-ii",
        ),
        configuration_check=security_configuration_error,
    ),
)


def _run_check(check: Check, repository: Path) -> CheckResult:
    if check.configuration_check is not None:
        error = check.configuration_check(repository)
        if error is not None:
            return CheckResult(
                name=check.name,
                exit_code=CONFIGURATION_EXIT,
                stdout="",
                stderr=f"{error}\n",
            )
    try:
        completed = subprocess.run(
            check.command,
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CheckResult(
            name=check.name,
            exit_code=CONFIGURATION_EXIT,
            stdout="",
            stderr=f"unable to start child command: {error}\n",
        )
    return CheckResult(
        name=check.name,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_fast_checks(repository: Path) -> FastCheckRun:
    required_paths = (RUFF_CONFIG, PYRIGHT_CONFIG, INSTALL_SANDBOX)
    missing = [path for path in required_paths if not (repository / path).exists()]
    if missing:
        return FastCheckRun(
            results=(),
            configuration_error="missing " + ", ".join(missing),
        )
    return FastCheckRun(
        results=tuple(_run_check(check, repository) for check in FAST_CHECKS),
    )
