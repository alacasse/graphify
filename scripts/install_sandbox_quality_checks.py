"""Construction and execution of independent install-sandbox fast checks."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYRIGHT_CONFIG,
    PYTHON_VERSION,
    security_configuration_error,
    typing_configuration_error,
)

CONFIGURATION_EXIT = 2
RUFF_CONFIG = "ruff.install-sandbox.toml"
FROZEN_PYTHON_RUN = ("uv", "run", "--frozen", "--python", PYTHON_VERSION)
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
class FastCheckResults:
    results: tuple[CheckResult, ...]


@dataclass(frozen=True)
class FastCheckConfigurationError:
    message: str


type FastCheckRun = FastCheckResults | FastCheckConfigurationError


FAST_CHECKS = (
    Check(
        name="ruff-format",
        command=(
            *FROZEN_PYTHON_RUN,
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
            *FROZEN_PYTHON_RUN,
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
            *FROZEN_PYTHON_RUN,
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
            *FROZEN_PYTHON_RUN,
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
        return FastCheckConfigurationError(message="missing " + ", ".join(missing))
    return FastCheckResults(
        results=tuple(_run_check(check, repository) for check in FAST_CHECKS),
    )
