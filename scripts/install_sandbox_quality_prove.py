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

PROOF_MARKER = "install_sandbox_proof"
PROOF_TEST_ROOT = "tests/quality_gate"


@dataclass(frozen=True)
class ProofRequirement:
    identifier: str
    description: str


PROOF_REQUIREMENTS = (
    ProofRequirement(
        "live-ci-command-ownership",
        "live CI command ownership",
    ),
    ProofRequirement(
        "ci-local-command-owner-drift",
        "CI and local command-owner drift",
    ),
    ProofRequirement(
        "contributor-guidance-alignment",
        "contributor guidance alignment",
    ),
    ProofRequirement(
        "complete-gate-installation-responsibilities",
        "complete gate installation responsibilities",
    ),
    ProofRequirement(
        "construction-branch-coverage",
        "construction branch coverage",
    ),
    ProofRequirement(
        "cutover-evidence-remaining-tree-coverage",
        "cutover evidence and remaining-tree coverage",
    ),
    ProofRequirement(
        "repository-warning-rejection",
        "repository warning rejection",
    ),
    ProofRequirement(
        "dependency-audit-failure-propagation",
        "pip-audit and independent failure propagation",
    ),
    ProofRequirement(
        "configuration-preflight-independence",
        "configuration preflight independence",
    ),
    ProofRequirement(
        "dependency-lock-mutation-detection",
        "dependency-lock mutation detection",
    ),
    ProofRequirement(
        "dependency-lock-restore-detection",
        "dependency-lock restore detection",
    ),
    ProofRequirement(
        "complete-aggregate-exits",
        "complete timeout and configuration exits",
    ),
    ProofRequirement(
        "missing-evidence-coverage-threshold",
        "missing evidence and coverage threshold",
    ),
    ProofRequirement(
        "replacement-coverage-exclusion-rejection",
        "replacement coverage exclusion rejection",
    ),
    ProofRequirement(
        "cutover-legacy-coverage-exclusion-rejection",
        "cutover legacy coverage exclusion rejection",
    ),
    ProofRequirement(
        "typed-docker-evidence",
        "typed Docker evidence boundary",
    ),
    ProofRequirement(
        "docker-selection-positive",
        "Docker selection positive path",
    ),
    ProofRequirement(
        "docker-finding-propagation",
        "raw Docker finding propagation",
    ),
    ProofRequirement(
        "docker-timeout",
        "Docker timeout propagation",
    ),
    ProofRequirement(
        "docker-classifier-publication-failure",
        "Docker classifier and publication failure propagation",
    ),
    ProofRequirement(
        "docker-configuration-exit",
        "Docker configuration exit",
    ),
    ProofRequirement(
        "gate-installation-non-applicability",
        "gate-installation non-applicability",
    ),
    ProofRequirement(
        "missing-construction-evidence",
        "missing construction evidence",
    ),
    ProofRequirement(
        "one-missing-construction-evidence-class",
        "one missing construction evidence class",
    ),
    ProofRequirement(
        "complete-construction-evidence",
        "complete construction evidence",
    ),
    ProofRequirement(
        "premature-behavioral-evidence",
        "premature Behavioral Evidence rejection",
    ),
    ProofRequirement(
        "partial-legacy-deletion",
        "partial legacy deletion rejection",
    ),
    ProofRequirement(
        "partial-caller-switch",
        "partial caller switch rejection",
    ),
    ProofRequirement(
        "cutover-missing-behavioral",
        "cutover missing Behavioral Evidence",
    ),
    ProofRequirement(
        "complete-atomic-cutover-evidence",
        "complete atomic cutover evidence",
    ),
    ProofRequirement(
        "applicable-replacement-test-lint-paths",
        "applicable replacement-test lint paths",
    ),
    ProofRequirement(
        "declared-path-static-analysis",
        "declared path static-analysis coverage",
    ),
    ProofRequirement(
        "escaped-static-analysis-path",
        "escaped static-analysis configuration path rejection",
    ),
    ProofRequirement(
        "replacement-test-strict-typing",
        "replacement-test strict typing scope",
    ),
    ProofRequirement(
        "typing-violation",
        "typing violation",
    ),
    ProofRequirement(
        "bandit-violation",
        "Bandit violation",
    ),
    ProofRequirement(
        "typing-configuration-drift",
        "typing configuration drift",
    ),
    ProofRequirement(
        "static-analysis-baseline-lock",
        "accepted static-analysis baseline and lock",
    ),
    ProofRequirement(
        "corrected-static-analysis",
        "corrected static-analysis fixture",
    ),
    ProofRequirement(
        "formatting-violation",
        "formatting violation",
    ),
    ProofRequirement(
        "lint-violation",
        "lint violation",
    ),
    ProofRequirement(
        "complexity-violation",
        "complexity violation",
    ),
    ProofRequirement(
        "fast-configuration-failure-independence",
        "fast configuration failure independence",
    ),
)


@dataclass(frozen=True)
class ProveCheckResults:
    configuration: CheckResult
    proof: CheckResult
    lock: CheckResult


def _proof_marker_identifier(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    marker = decorator.func
    namespace = marker.value
    if (
        marker.attr != PROOF_MARKER
        or not isinstance(namespace, ast.Attribute)
        or namespace.attr != "mark"
        or not isinstance(namespace.value, ast.Name)
        or namespace.value.id != "pytest"
    ):
        return None
    if (
        len(decorator.args) != 1
        or decorator.keywords
        or not isinstance(decorator.args[0], ast.Constant)
        or not isinstance(decorator.args[0].value, str)
        or not decorator.args[0].value
    ):
        raise ValueError(f"{PROOF_MARKER} requires one non-empty string identifier")
    return decorator.args[0].value


def _proof_declarations(repository: Path) -> tuple[dict[str, list[str]], list[str]]:
    discovered: dict[str, list[str]] = {}
    problems: list[str] = []
    for path in sorted((repository / PROOF_TEST_ROOT).glob("test_*.py")):
        relative = path.relative_to(repository).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as error:
            problems.append(f"unable to inspect proof declarations in {relative}: {error}")
            continue
        for node in tree.body:
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) or not node.name.startswith("test_"):
                continue
            for decorator in node.decorator_list:
                try:
                    identifier = _proof_marker_identifier(decorator)
                except ValueError as error:
                    problems.append(
                        f"invalid proof declaration at {relative}:{node.lineno}: {error}"
                    )
                    continue
                if identifier is not None:
                    discovered.setdefault(identifier, []).append(f"{relative}:{node.lineno}")
    return discovered, problems


def _proof_inventory_problems(
    declared: dict[str, ProofRequirement],
    discovered: dict[str, list[str]],
) -> list[str]:
    problems = []

    missing = sorted(set(declared) - set(discovered))
    unknown = sorted(set(discovered) - set(declared))
    duplicate = sorted(
        identifier for identifier, locations in discovered.items() if len(locations) > 1
    )
    if missing:
        problems.append(
            "missing required proof scenarios: "
            + ", ".join(declared[identifier].description for identifier in missing)
        )
    if unknown:
        problems.append("unknown proof requirements: " + ", ".join(unknown))
    if duplicate:
        problems.append(
            "duplicate proof requirements: "
            + ", ".join(
                f"{identifier} ({', '.join(discovered[identifier])})" for identifier in duplicate
            )
        )
    return problems


def _declared_proof_requirements() -> tuple[dict[str, ProofRequirement], list[str]]:
    declared: dict[str, ProofRequirement] = {}
    duplicate: set[str] = set()
    for requirement in PROOF_REQUIREMENTS:
        if requirement.identifier in declared:
            duplicate.add(requirement.identifier)
        else:
            declared[requirement.identifier] = requirement
    problems = []
    if duplicate:
        problems.append("duplicate declared proof requirements: " + ", ".join(sorted(duplicate)))
    return declared, problems


def _proof_configuration(repository: Path) -> CheckResult:
    declared, problems = _declared_proof_requirements()
    discovered, declaration_problems = _proof_declarations(repository)
    problems.extend(declaration_problems)
    problems.extend(_proof_inventory_problems(declared, discovered))
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
            PROOF_TEST_ROOT,
            "-m",
            PROOF_MARKER,
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
