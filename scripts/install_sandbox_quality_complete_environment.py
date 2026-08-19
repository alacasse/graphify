"""Observe complete-gate configuration inputs and dependency-lock stability."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    RUFF_CONFIG,
    CheckResult,
    CheckStatus,
)
from scripts.install_sandbox_quality_lock import (
    LOCKFILE,
    DependencyLockObserver,
    capture_dependency_lock,
)
from scripts.install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYPROJECT_CONFIG,
    PYRIGHT_CONFIG,
)

REQUIRED_PATHS = (RUFF_CONFIG, PYRIGHT_CONFIG, PYPROJECT_CONFIG, LOCKFILE, INSTALL_SANDBOX)


@dataclass(frozen=True)
class CompleteGateEnvironment:
    configuration: CheckResult
    dependency_lock: DependencyLockObserver


def inspect_complete_gate_environment(repository: Path) -> CompleteGateEnvironment:
    missing = tuple(path for path in REQUIRED_PATHS if not (repository / path).exists())
    configuration_error = "missing " + ", ".join(missing) if missing else None
    configuration = CheckResult(
        name="complete-configuration",
        status=CheckStatus.PASS if configuration_error is None else CheckStatus.FAIL,
        exit_code=None if configuration_error is None else CONFIGURATION_EXIT,
        stdout="",
        stderr="" if configuration_error is None else f"{configuration_error}\n",
        configuration_error=configuration_error is not None,
    )

    return CompleteGateEnvironment(
        configuration=configuration,
        dependency_lock=capture_dependency_lock(
            repository,
            operation="complete gate",
        ),
    )
