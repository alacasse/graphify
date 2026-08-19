"""Construct and execute the complete gate's non-Docker subprocess checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scripts.install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    FROZEN_PYTHON_RUN,
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
from scripts.install_sandbox_quality_phase import EvidencePolicy, GatePhasePolicy, policy_for_state
from scripts.install_sandbox_quality_policy import coverage_configuration_error
from scripts.install_sandbox_quality_state import RepositoryState, RepositoryStateFailure

UNIT_EVIDENCE = "tests/install_sandbox/unit"
COMPONENT_EVIDENCE = "tests/install_sandbox/component"
BEHAVIORAL_EVIDENCE = "tests/install_sandbox/behavioral"
ChildCompleted = Callable[[], None]


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


def _complete_behavioral_result(
    policy: GatePhasePolicy,
    repository: Path,
    child_completed: ChildCompleted,
) -> CheckResult:
    applicability = assess_behavioral_evidence(
        policy,
        repository,
        child_completed=child_completed,
    )
    if applicability.status is not CheckStatus.APPLICABLE:
        return applicability
    return run_required_pytest(
        pytest_check("behavioral-evidence", BEHAVIORAL_EVIDENCE),
        repository,
        child_completed=child_completed,
    )


def _complete_evidence_results(
    policy: GatePhasePolicy,
    repository: Path,
    child_completed: ChildCompleted,
) -> tuple[CheckResult, ...]:
    if policy.replacement_evidence is EvidencePolicy.NOT_APPLICABLE:
        return (
            not_run("unit-evidence", CheckStatus.NOT_APPLICABLE),
            not_run("component-evidence", CheckStatus.NOT_APPLICABLE),
            assess_behavioral_evidence(
                policy,
                repository,
                child_completed=child_completed,
            ),
            not_run("replacement-coverage", CheckStatus.NOT_APPLICABLE),
        )
    return (
        run_check(
            pytest_check("unit-evidence-collection", UNIT_EVIDENCE, collect_only=True),
            repository,
            child_completed=child_completed,
        ),
        run_check(
            pytest_check("component-evidence-collection", COMPONENT_EVIDENCE, collect_only=True),
            repository,
            child_completed=child_completed,
        ),
        run_required_pytest(
            _coverage_check(),
            repository,
            child_completed=child_completed,
        ),
        _complete_behavioral_result(policy, repository, child_completed),
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


def _state_dependent_results(
    state: RepositoryState | RepositoryStateFailure,
    repository: Path,
    child_completed: ChildCompleted,
) -> tuple[CheckResult, ...]:
    if isinstance(state, RepositoryStateFailure):
        return (
            CheckResult(
                name="repository-state",
                status=CheckStatus.FAIL,
                exit_code=1,
                stdout="",
                stderr="; ".join(state.problems) + "\n",
            ),
        )
    policy = policy_for_state(state)
    return (
        _repository_state_result(state),
        *(
            run_check(check, repository, child_completed=child_completed)
            for check in static_checks(state, repository)
        ),
        _configuration_result("coverage-policy", coverage_configuration_error(repository, policy)),
        *_complete_evidence_results(policy, repository, child_completed),
    )


def run_complete_check_set(
    state: RepositoryState | RepositoryStateFailure,
    repository: Path,
    child_completed: ChildCompleted,
) -> tuple[CheckResult, ...]:
    """Run all independent non-Docker responsibilities before aggregation."""

    return (
        *_state_dependent_results(state, repository, child_completed),
        run_check(
            _dependency_audit_check(),
            repository,
            child_completed=child_completed,
        ),
        run_warning_clean_pytest(
            _repository_suite_check(),
            repository,
            child_completed=child_completed,
        ),
    )
