"""Complete-tier orchestration for the install-sandbox development gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    FROZEN_PYTHON_RUN,
    PYRIGHT_CONFIG,
    RUFF_CONFIG,
    Check,
    CheckResult,
    CheckStatus,
    assess_behavioral_evidence,
    not_run,
    pytest_check,
    run_check,
    run_required_pytest,
    run_warning_clean_pytest,
    static_checks,
)
from install_sandbox_quality_docker import DockerGateRun, run_docker_gate
from install_sandbox_quality_evidence import FullDockerSelection
from install_sandbox_quality_policy import (
    INSTALL_SANDBOX,
    PYPROJECT_CONFIG,
    coverage_configuration_error,
)
from install_sandbox_quality_state import (
    GatePhase,
    RepositoryState,
    RepositoryStateFailure,
    assess_repository_state,
)

LOCKFILE = "uv.lock"
UNIT_EVIDENCE = "tests/install_sandbox/unit"
COMPONENT_EVIDENCE = "tests/install_sandbox/component"
BEHAVIORAL_EVIDENCE = "tests/install_sandbox/behavioral"


@dataclass(frozen=True)
class CompleteCheckResults:
    checks: tuple[CheckResult, ...]
    docker: DockerGateRun
    lock: CheckResult


@dataclass(frozen=True)
class CompleteCheckConfigurationError:
    message: str


type CompleteCheckRun = CompleteCheckResults | CompleteCheckConfigurationError


def _configuration_result(name: str, error: str | None) -> CheckResult:
    return CheckResult(
        name=name,
        status=CheckStatus.PASS if error is None else CheckStatus.FAIL,
        exit_code=None if error is None else CONFIGURATION_EXIT,
        stdout="",
        stderr="" if error is None else f"{error}\n",
        configuration_error=error is not None,
    )


def _repository_state_result(state: RepositoryState) -> CheckResult:
    return CheckResult(
        name="repository-state",
        status=CheckStatus.PASS,
        exit_code=None,
        stdout=f"repository state: {state.phase.value}\n",
        stderr="",
    )


def _coverage_check() -> Check:
    base = pytest_check("replacement-coverage", UNIT_EVIDENCE, COMPONENT_EVIDENCE)
    return Check(
        name=base.name,
        command=(
            *base.command,
            "--cov=tools.install_sandbox",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-fail-under=90",
        ),
        exit_two_is_configuration=False,
    )


def _complete_behavioral_result(state: RepositoryState, repository: Path) -> CheckResult:
    applicability = assess_behavioral_evidence(state, repository)
    if applicability.status is not CheckStatus.APPLICABLE:
        return applicability
    return run_required_pytest(
        pytest_check("behavioral-evidence", BEHAVIORAL_EVIDENCE),
        repository,
    )


def _complete_evidence_results(
    state: RepositoryState,
    repository: Path,
) -> tuple[CheckResult, ...]:
    if state.phase is GatePhase.GATE_INSTALLATION:
        return (
            not_run("unit-evidence", CheckStatus.NOT_APPLICABLE),
            not_run("component-evidence", CheckStatus.NOT_APPLICABLE),
            assess_behavioral_evidence(state, repository),
            not_run("replacement-coverage", CheckStatus.NOT_APPLICABLE),
        )
    return (
        run_check(
            pytest_check("unit-evidence-collection", UNIT_EVIDENCE, collect_only=True),
            repository,
        ),
        run_check(
            pytest_check("component-evidence-collection", COMPONENT_EVIDENCE, collect_only=True),
            repository,
        ),
        run_required_pytest(_coverage_check(), repository),
        _complete_behavioral_result(state, repository),
    )


def _dependency_audit_check() -> Check:
    return Check(
        name="dependency-audit",
        command=(*FROZEN_PYTHON_RUN, "pip-audit", "--strict", "--progress-spinner", "off"),
        exit_two_is_configuration=False,
    )


def _repository_suite_check() -> Check:
    base = pytest_check("repository-suite", "tests/")
    return Check(
        name=base.name,
        command=(
            *base.command,
            f"--ignore={UNIT_EVIDENCE}",
            f"--ignore={COMPONENT_EVIDENCE}",
            f"--ignore={BEHAVIORAL_EVIDENCE}",
        ),
        exit_two_is_configuration=False,
    )


def _lock_result(lockfile: Path, expected: bytes) -> CheckResult:
    try:
        unchanged = lockfile.read_bytes() == expected
    except OSError as error:
        return CheckResult(
            name="dependency-lock",
            status=CheckStatus.FAIL,
            exit_code=1,
            stdout="",
            stderr=f"unable to verify unchanged {LOCKFILE}: {error}\n",
        )
    return CheckResult(
        name="dependency-lock",
        status=CheckStatus.PASS if unchanged else CheckStatus.FAIL,
        exit_code=None if unchanged else 1,
        stdout="",
        stderr="" if unchanged else f"{LOCKFILE} changed during complete gate\n",
    )


def run_complete_checks(repository: Path) -> CompleteCheckRun:
    required_paths = (RUFF_CONFIG, PYRIGHT_CONFIG, PYPROJECT_CONFIG, LOCKFILE, INSTALL_SANDBOX)
    missing = [path for path in required_paths if not (repository / path).exists()]
    if missing:
        return CompleteCheckConfigurationError(message="missing " + ", ".join(missing))
    lockfile = repository / LOCKFILE
    try:
        original_lock = lockfile.read_bytes()
    except OSError as error:
        return CompleteCheckConfigurationError(message=f"unable to read {LOCKFILE}: {error}")

    state = assess_repository_state(repository)
    if isinstance(state, RepositoryStateFailure):
        state_results = (
            CheckResult(
                name="repository-state",
                status=CheckStatus.FAIL,
                exit_code=1,
                stdout="",
                stderr="; ".join(state.problems) + "\n",
            ),
        )
    else:
        state_results = (
            _repository_state_result(state),
            *(run_check(check, repository) for check in static_checks(state, repository)),
            _configuration_result(
                "coverage-policy",
                coverage_configuration_error(repository, state.phase),
            ),
            *_complete_evidence_results(state, repository),
        )

    checks = (
        *state_results,
        run_check(_dependency_audit_check(), repository),
        run_warning_clean_pytest(_repository_suite_check(), repository),
    )
    docker = run_docker_gate(repository, FullDockerSelection())
    return CompleteCheckResults(
        checks=checks,
        docker=docker,
        lock=_lock_result(lockfile, original_lock),
    )
