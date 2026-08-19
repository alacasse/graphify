"""Construction and execution of independent install-sandbox fast checks."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYRIGHT_CONFIG,
    PYTHON_VERSION,
    security_configuration_error,
    typing_configuration_error,
)
from install_sandbox_quality_state import (
    GatePhase,
    RepositoryState,
    RepositoryStateFailure,
    assess_repository_state,
)

CONFIGURATION_EXIT = 2
RUFF_CONFIG = "ruff.install-sandbox.toml"
FROZEN_PYTHON_RUN = ("uv", "run", "--frozen", "--python", PYTHON_VERSION)
ConfigurationCheck = Callable[[Path], str | None]
NONPASSING_PYTEST_OUTCOME = re.compile(r"\b(?:skipped|xfailed|xpassed)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    configuration_check: ConfigurationCheck | None = None
    exit_two_is_configuration: bool = True


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    exit_code: int | None
    stdout: str
    stderr: str
    configuration_error: bool = False


class CheckStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT APPLICABLE"


@dataclass(frozen=True)
class FastCheckResults:
    results: tuple[CheckResult, ...]


@dataclass(frozen=True)
class FastCheckConfigurationError:
    message: str


type FastCheckRun = FastCheckResults | FastCheckConfigurationError


def _fast_checks(state: RepositoryState, repository: Path) -> tuple[Check, ...]:
    existing_paths = tuple(
        path for path in state.static_analysis_paths if (repository / path).exists()
    )
    return (
        Check(
            name="ruff-format",
            command=(
                *FROZEN_PYTHON_RUN,
                "ruff",
                "format",
                "--config",
                RUFF_CONFIG,
                "--check",
                *existing_paths,
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
                *existing_paths,
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
                status=CheckStatus.FAIL,
                exit_code=CONFIGURATION_EXIT,
                stdout="",
                stderr=f"{error}\n",
                configuration_error=True,
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
            status=CheckStatus.FAIL,
            exit_code=CONFIGURATION_EXIT,
            stdout="",
            stderr=f"unable to start child command: {error}\n",
            configuration_error=True,
        )
    return CheckResult(
        name=check.name,
        status=CheckStatus.PASS if completed.returncode == 0 else CheckStatus.FAIL,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        configuration_error=completed.returncode == CONFIGURATION_EXIT
        and check.exit_two_is_configuration,
    )


def _not_run(name: str, status: CheckStatus) -> CheckResult:
    return CheckResult(
        name=name,
        status=status,
        exit_code=None,
        stdout="",
        stderr="",
    )


def _pytest_check(name: str, *selectors: str, collect_only: bool = False) -> Check:
    collection_arguments = ("--collect-only",) if collect_only else ()
    return Check(
        name=name,
        command=(
            *FROZEN_PYTHON_RUN,
            "pytest",
            *selectors,
            *collection_arguments,
            "-q",
            "--tb=short",
            "--strict-config",
            "--strict-markers",
            "-W",
            "error",
        ),
        exit_two_is_configuration=False,
    )


def _run_required_evidence(check: Check, repository: Path) -> CheckResult:
    result = _run_check(check, repository)
    output = result.stdout + result.stderr
    if result.status is not CheckStatus.PASS or not NONPASSING_PYTEST_OUTCOME.search(output):
        return result
    return CheckResult(
        name=result.name,
        status=CheckStatus.FAIL,
        exit_code=1,
        stdout=result.stdout,
        stderr=result.stderr + "required evidence produced a non-passing pytest outcome\n",
    )


def _behavioral_result(state: RepositoryState, repository: Path) -> CheckResult:
    behavioral = repository / "tests/install_sandbox/behavioral"
    candidates = sorted(
        {
            *behavioral.rglob("test_*.py"),
            *behavioral.rglob("*_test.py"),
        }
    )
    if not candidates:
        if state.phase is not GatePhase.ATOMIC_CUTOVER:
            return _not_run("behavioral-evidence", CheckStatus.NOT_APPLICABLE)
        return CheckResult(
            name="behavioral-evidence",
            status=CheckStatus.FAIL,
            exit_code=1,
            stdout="",
            stderr="Atomic Cutover requires non-empty Behavioral Evidence\n",
        )
    collection = _run_check(
        _pytest_check("behavioral-evidence", behavioral.as_posix(), collect_only=True),
        repository,
    )
    if collection.exit_code == 5:
        if state.phase is not GatePhase.ATOMIC_CUTOVER:
            return _not_run("behavioral-evidence", CheckStatus.NOT_APPLICABLE)
        return CheckResult(
            name=collection.name,
            status=CheckStatus.FAIL,
            exit_code=collection.exit_code,
            stdout=collection.stdout,
            stderr=collection.stderr + "Atomic Cutover requires non-empty Behavioral Evidence\n",
        )
    if collection.status is CheckStatus.FAIL:
        return collection
    if state.phase is GatePhase.ATOMIC_CUTOVER:
        return CheckResult(
            name=collection.name,
            status=CheckStatus.APPLICABLE,
            exit_code=collection.exit_code,
            stdout=collection.stdout,
            stderr=collection.stderr,
        )
    return CheckResult(
        name=collection.name,
        status=CheckStatus.FAIL,
        exit_code=1,
        stdout=collection.stdout,
        stderr=collection.stderr + "Behavioral Evidence is prohibited before Atomic Cutover\n",
    )


def _evidence_results(state: RepositoryState, repository: Path) -> tuple[CheckResult, ...]:
    if state.phase is GatePhase.GATE_INSTALLATION:
        return (
            _not_run("unit-evidence", CheckStatus.NOT_APPLICABLE),
            _not_run("component-evidence", CheckStatus.NOT_APPLICABLE),
            _behavioral_result(state, repository),
            _not_run("replacement-coverage", CheckStatus.NOT_APPLICABLE),
        )
    unit = "tests/install_sandbox/unit"
    component = "tests/install_sandbox/component"
    return (
        _run_check(_pytest_check("unit-evidence-collection", unit, collect_only=True), repository),
        _run_check(
            _pytest_check("component-evidence-collection", component, collect_only=True), repository
        ),
        _run_required_evidence(
            _pytest_check("unit-component-evidence", unit, component), repository
        ),
        _behavioral_result(state, repository),
        _not_run("replacement-coverage", CheckStatus.APPLICABLE),
    )


def run_fast_checks(repository: Path) -> FastCheckRun:
    required_paths = (RUFF_CONFIG, PYRIGHT_CONFIG, INSTALL_SANDBOX)
    missing = [path for path in required_paths if not (repository / path).exists()]
    if missing:
        return FastCheckConfigurationError(message="missing " + ", ".join(missing))
    state = assess_repository_state(repository)
    if isinstance(state, RepositoryStateFailure):
        return FastCheckResults(
            results=(
                CheckResult(
                    name="repository-state",
                    status=CheckStatus.FAIL,
                    exit_code=1,
                    stdout="",
                    stderr="; ".join(state.problems) + "\n",
                ),
            )
        )
    state_result = CheckResult(
        name="repository-state",
        status=CheckStatus.PASS,
        exit_code=None,
        stdout=f"repository state: {state.phase.value}\n",
        stderr="",
    )
    return FastCheckResults(
        results=(
            state_result,
            *(_run_check(check, repository) for check in _fast_checks(state, repository)),
            *_evidence_results(state, repository),
        ),
    )
