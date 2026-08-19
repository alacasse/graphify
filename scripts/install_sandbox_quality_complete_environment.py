"""Observe complete-gate configuration inputs and dependency-lock stability."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    RUFF_CONFIG,
    CheckResult,
    CheckStatus,
)
from scripts.install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYPROJECT_CONFIG,
    PYRIGHT_CONFIG,
)

LOCKFILE = "uv.lock"
REQUIRED_PATHS = (RUFF_CONFIG, PYRIGHT_CONFIG, PYPROJECT_CONFIG, LOCKFILE, INSTALL_SANDBOX)


@dataclass
class CapturedDependencyLock:
    path: Path
    expected: bytes
    _drift_error: str | None = field(default=None, init=False)

    def observe(self) -> None:
        """Record lock drift after a child; a later restore cannot clear it."""

        if self._drift_error is not None:
            return
        try:
            actual = self.path.read_bytes()
        except OSError as error:
            self._drift_error = f"unable to verify unchanged {LOCKFILE}: {error}"
            return
        if actual != self.expected:
            self._drift_error = f"{LOCKFILE} changed during complete gate"

    def result(self) -> CheckResult:
        error = self._drift_error
        return CheckResult(
            name="dependency-lock",
            status=CheckStatus.PASS if error is None else CheckStatus.FAIL,
            exit_code=None if error is None else 1,
            stdout="",
            stderr="" if error is None else f"{error}\n",
        )


@dataclass(frozen=True)
class UnavailableDependencyLock:
    path: Path
    capture_error: str

    def __post_init__(self) -> None:
        if not self.capture_error.strip():
            raise ValueError("dependency-lock capture error must not be empty")

    def observe(self) -> None:
        """There is no captured snapshot to compare after child completion."""

    def result(self) -> CheckResult:
        return CheckResult(
            name="dependency-lock",
            status=CheckStatus.FAIL,
            exit_code=CONFIGURATION_EXIT,
            stdout="",
            stderr=f"{self.capture_error}\n",
            configuration_error=True,
        )


type DependencyLockObserver = CapturedDependencyLock | UnavailableDependencyLock


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

    lockfile = repository / LOCKFILE
    try:
        dependency_lock: DependencyLockObserver = CapturedDependencyLock(
            path=lockfile,
            expected=lockfile.read_bytes(),
        )
    except OSError as error:
        dependency_lock = UnavailableDependencyLock(
            path=lockfile,
            capture_error=f"unable to read {LOCKFILE}: {error}",
        )
    return CompleteGateEnvironment(
        configuration=configuration,
        dependency_lock=dependency_lock,
    )
