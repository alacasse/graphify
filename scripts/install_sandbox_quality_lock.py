"""Capture and observe dependency-lock immutability for quality commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    CheckResult,
    CheckStatus,
)

LOCKFILE = "uv.lock"


@dataclass
class CapturedDependencyLock:
    path: Path
    expected: bytes
    operation: str
    _drift_error: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("dependency-lock operation must not be empty")

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
            self._drift_error = f"{LOCKFILE} changed during {self.operation}"

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


def capture_dependency_lock(repository: Path, *, operation: str) -> DependencyLockObserver:
    path = repository / LOCKFILE
    try:
        return CapturedDependencyLock(
            path=path,
            expected=path.read_bytes(),
            operation=operation,
        )
    except OSError as error:
        return UnavailableDependencyLock(
            path=path,
            capture_error=f"unable to read {LOCKFILE}: {error}",
        )
