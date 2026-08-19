"""Operational proof orchestration for the install-sandbox quality gate."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from scripts.install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    CheckResult,
    CheckStatus,
    pytest_check,
    run_required_pytest,
)
from scripts.install_sandbox_quality_lock import capture_dependency_lock

PROOF_SELF_TEST = "tests/quality_gate/test_prove_gate.py"


@dataclass(frozen=True)
class ProofRequirement:
    description: str
    module: str
    test_name: str

    @property
    def selector(self) -> str:
        return f"{self.module}::{self.test_name}"


def _requirement(description: str, module: str, test_name: str) -> ProofRequirement:
    return ProofRequirement(
        description=description,
        module=f"tests/quality_gate/{module}",
        test_name=test_name,
    )


PROOF_REQUIREMENTS = (
    _requirement(
        "live CI command ownership",
        "test_ci_configuration.py",
        "test_every_pull_request_runs_the_canonical_fast_gate",
    ),
    _requirement(
        "CI and local command-owner drift",
        "test_ci_configuration.py",
        "test_temporary_ci_and_local_command_owner_drift_is_detected",
    ),
    _requirement(
        "contributor guidance alignment",
        "test_ci_configuration.py",
        "test_contributor_guidance_describes_the_same_quality_gate_contract",
    ),
    _requirement(
        "complete gate installation responsibilities",
        "test_complete_gate.py",
        "test_complete_gate_runs_every_gate_installation_responsibility",
    ),
    _requirement(
        "construction branch coverage",
        "test_complete_gate.py",
        "test_complete_gate_replaces_fast_evidence_with_branch_coverage_during_construction",
    ),
    _requirement(
        "cutover evidence and remaining-tree coverage",
        "test_complete_gate.py",
        "test_complete_gate_runs_all_evidence_and_remaining_tree_coverage_at_cutover",
    ),
    _requirement(
        "repository warning rejection",
        "test_complete_gate.py",
        "test_complete_gate_rejects_repository_suite_warnings",
    ),
    _requirement(
        "pip-audit and independent failure propagation",
        "test_complete_gate.py",
        "test_complete_gate_preserves_independent_failures_before_aggregation",
    ),
    _requirement(
        "configuration preflight independence",
        "test_complete_gate.py",
        "test_complete_gate_runs_independent_checks_after_configuration_preflight_failure",
    ),
    _requirement(
        "dependency-lock mutation detection",
        "test_complete_gate.py",
        "test_complete_gate_fails_if_a_child_changes_the_dependency_lock",
    ),
    _requirement(
        "dependency-lock restore detection",
        "test_complete_gate.py",
        "test_complete_gate_fails_if_a_later_child_restores_the_dependency_lock",
    ),
    _requirement(
        "complete timeout and configuration exits",
        "test_complete_gate.py",
        "test_complete_gate_preserves_approved_aggregate_exits",
    ),
    _requirement(
        "missing evidence and coverage threshold",
        "test_complete_gate.py",
        "test_complete_gate_blocks_missing_evidence_or_insufficient_branch_coverage",
    ),
    _requirement(
        "replacement coverage exclusion rejection",
        "test_complete_gate.py",
        "test_complete_gate_rejects_a_replacement_path_in_legacy_coverage_exclusions",
    ),
    _requirement(
        "cutover legacy coverage exclusion rejection",
        "test_complete_gate.py",
        "test_complete_gate_rejects_legacy_coverage_exclusions_at_cutover",
    ),
    _requirement(
        "typed Docker evidence boundary",
        "test_docker_evidence.py",
        "test_evidence_consumer_returns_a_typed_passed_variant",
    ),
    _requirement(
        "Docker selection positive path",
        "test_docker_gate.py",
        "test_docker_gate_uses_approved_targeted_and_full_selection",
    ),
    _requirement(
        "raw Docker finding propagation",
        "test_docker_gate.py",
        "test_docker_gate_preserves_raw_findings_but_blocks_unapproved_findings",
    ),
    _requirement(
        "Docker timeout propagation",
        "test_docker_gate.py",
        "test_docker_gate_preserves_the_approved_timeout_exit",
    ),
    _requirement(
        "Docker classifier and publication failure propagation",
        "test_docker_gate.py",
        "test_docker_gate_blocks_classifier_or_publication_failure",
    ),
    _requirement(
        "Docker configuration exit",
        "test_docker_gate.py",
        "test_docker_gate_distinguishes_runner_usage_failure",
    ),
    _requirement(
        "gate-installation non-applicability",
        "test_evidence_applicability.py",
        "test_fast_gate_reports_replacement_evidence_not_applicable_during_gate_installation",
    ),
    _requirement(
        "missing construction evidence",
        "test_evidence_applicability.py",
        "test_fast_gate_reports_missing_construction_evidence_as_check_failure",
    ),
    _requirement(
        "one missing construction evidence class",
        "test_evidence_applicability.py",
        "test_fast_gate_rejects_empty_component_evidence",
    ),
    _requirement(
        "complete construction evidence",
        "test_evidence_applicability.py",
        "test_fast_gate_requires_and_runs_construction_evidence",
    ),
    _requirement(
        "premature Behavioral Evidence rejection",
        "test_evidence_applicability.py",
        "test_fast_gate_rejects_behavioral_evidence_before_cutover",
    ),
    _requirement(
        "partial legacy deletion rejection",
        "test_evidence_applicability.py",
        "test_fast_gate_rejects_partial_legacy_deletion",
    ),
    _requirement(
        "partial caller switch rejection",
        "test_evidence_applicability.py",
        "test_fast_gate_rejects_partial_caller_switch",
    ),
    _requirement(
        "cutover missing Behavioral Evidence",
        "test_evidence_applicability.py",
        "test_fast_gate_rejects_cutover_without_behavioral_evidence",
    ),
    _requirement(
        "complete atomic cutover evidence",
        "test_evidence_applicability.py",
        "test_fast_gate_recognizes_complete_atomic_cutover",
    ),
    _requirement(
        "applicable replacement-test lint paths",
        "test_evidence_applicability.py",
        "test_fast_gate_lints_applicable_evidence_paths",
    ),
    _requirement(
        "declared path static-analysis coverage",
        "test_fast_typing_security.py",
        "test_fast_gate_rejects_new_production_file_outside_strict_scope",
    ),
    _requirement(
        "replacement-test strict typing scope",
        "test_fast_typing_security.py",
        "test_fast_gate_rejects_relaxed_replacement_test_typing_scope",
    ),
    _requirement(
        "typing violation",
        "test_fast_typing_security.py",
        "test_fast_gate_rejects_strict_type_error",
    ),
    _requirement(
        "Bandit violation",
        "test_fast_typing_security.py",
        "test_fast_gate_rejects_blocking_security_finding",
    ),
    _requirement(
        "typing configuration drift",
        "test_fast_typing_security.py",
        "test_fast_gate_rejects_pyright_runtime_drift",
    ),
    _requirement(
        "accepted static-analysis baseline and lock",
        "test_fast_typing_security.py",
        "test_fast_gate_accepts_approved_baseline_without_changing_lock",
    ),
    _requirement(
        "corrected static-analysis fixture",
        "test_fast_ruff.py",
        "test_fast_gate_accepts_corrected_ruff_fixture",
    ),
    _requirement(
        "formatting violation",
        "test_fast_ruff.py",
        "test_fast_gate_reports_format_failure_after_running_lint",
    ),
    _requirement(
        "lint violation",
        "test_fast_ruff.py",
        "test_fast_gate_rejects_lint_violation",
    ),
    _requirement(
        "complexity violation",
        "test_fast_ruff.py",
        "test_fast_gate_enforces_all_approved_complexity_limits",
    ),
    _requirement(
        "fast configuration failure independence",
        "test_fast_ruff.py",
        "test_fast_gate_reports_every_child_before_configuration_exit",
    ),
)
PROOF_TEST_MODULES = tuple(sorted({item.module for item in PROOF_REQUIREMENTS}))


@dataclass(frozen=True)
class ProveCheckResults:
    configuration: CheckResult
    proof: CheckResult
    lock: CheckResult


def _proof_configuration(repository: Path) -> CheckResult:
    proof_root = repository / "tests" / "quality_gate"
    declared = set(PROOF_TEST_MODULES)
    discovered = {
        path.relative_to(repository).as_posix()
        for path in proof_root.glob("test_*.py")
        if path.relative_to(repository).as_posix() != PROOF_SELF_TEST
    }
    missing = sorted(declared - discovered)
    undeclared = sorted(discovered - declared)
    problems = []
    if missing:
        problems.append("missing proof modules: " + ", ".join(missing))
    if undeclared:
        problems.append("undeclared proof modules: " + ", ".join(undeclared))
    required_by_module = {
        module: tuple(
            requirement
            for requirement in PROOF_REQUIREMENTS
            if requirement.module == module
        )
        for module in PROOF_TEST_MODULES
    }
    missing_scenarios = []
    for module, requirements in required_by_module.items():
        path = repository / module
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=module)
        except (OSError, SyntaxError, UnicodeError) as error:
            problems.append(f"unable to inspect proof module {module}: {error}")
            continue
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing_scenarios.extend(
            requirement
            for requirement in requirements
            if requirement.test_name not in functions
        )
    if missing_scenarios:
        problems.append(
            "missing required proof scenarios: "
            + ", ".join(
                f"{requirement.description} ({requirement.selector})"
                for requirement in missing_scenarios
            )
        )
    error = "; ".join(problems)
    return CheckResult(
        name="prove-configuration",
        status=CheckStatus.PASS if not error else CheckStatus.FAIL,
        exit_code=None if not error else CONFIGURATION_EXIT,
        stdout="",
        stderr="" if not error else f"{error}\n",
        configuration_error=bool(error),
    )


def run_prove_checks(repository: Path) -> ProveCheckResults:
    """Run the declared proof suite and preserve lock immutability evidence."""

    configuration = _proof_configuration(repository)
    dependency_lock = capture_dependency_lock(repository, operation="prove")
    proof = run_required_pytest(
        pytest_check(
            "operational-proof",
            *PROOF_TEST_MODULES,
            exit_two_is_configuration=True,
        ),
        repository,
        child_completed=dependency_lock.observe,
    )
    dependency_lock.observe()
    return ProveCheckResults(
        configuration=configuration,
        proof=proof,
        lock=dependency_lock.result(),
    )
