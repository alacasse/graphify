"""Bind the Run Record and Diagnostic Manifest into typed terminal evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from scripts.install_sandbox_quality_manifest import (
    ProductFinding,
    ScenarioExpectation,
    ScenarioIdentity,
    load_artifact_object,
    validate_manifest_findings,
    validated_package_targets,
)
from tools.install_sandbox.models import Scope, TargetSpec
from tools.install_sandbox.specs import SpecError, load_catalog

RUN_RECORD = "run.json"
DIAGNOSTIC_MANIFEST = "manifest.json"
LEGACY_RUN_SCHEMA_VERSION = 1
CATALOG_DIRECTORY = Path("tools/install_sandbox/specs")


class RunOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class TargetedDockerSelection:
    target: str

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ValueError("Docker target must be a non-empty string")

    def runner_arguments(self) -> tuple[str, ...]:
        return ("--target", self.target)

    def evidence_value(self) -> dict[str, object]:
        return {"target": self.target, "all": False, "scope": "both"}


@dataclass(frozen=True)
class FullDockerSelection:
    def runner_arguments(self) -> tuple[str, ...]:
        return ("--all",)

    def evidence_value(self) -> dict[str, object]:
        return {"target": None, "all": True, "scope": "both"}


type DockerSelection = TargetedDockerSelection | FullDockerSelection


@dataclass(frozen=True)
class PassedEvidence:
    pass


@dataclass(frozen=True)
class FailedEvidence:
    findings: tuple[ProductFinding, ...]

    def __post_init__(self) -> None:
        if not self.findings:
            raise ValueError("failed evidence requires at least one Product Finding")


@dataclass(frozen=True)
class IncompleteEvidence:
    pass


@dataclass(frozen=True)
class InterruptedEvidence:
    pass


type TerminalEvidence = PassedEvidence | FailedEvidence | IncompleteEvidence | InterruptedEvidence


def _same_selection(value: object, expected: Mapping[str, object]) -> bool:
    return isinstance(value, dict) and value == expected


def _validate_run_record_binding(
    run_record: Mapping[str, object],
    repository: Path,
    bundle: Path,
    selection: DockerSelection,
    runner_exit: int,
) -> None:
    if run_record.get("schema_version") != LEGACY_RUN_SCHEMA_VERSION:
        raise ValueError("Run Record schema is missing or unsupported")
    _validate_run_record_identity(run_record)
    if not _same_selection(run_record.get("selection"), selection.evidence_value()):
        raise ValueError("Run Record selection does not match the requested validation")
    if run_record.get("repository") != str(repository):
        raise ValueError("Run Record repository does not match the validated checkout")
    if run_record.get("output") != str(bundle):
        raise ValueError("Run Record output does not match the Diagnostic Bundle")
    if run_record.get("exit_code") != runner_exit:
        raise ValueError("Run Record exit does not match the observed runner exit")


def _validate_run_record_identity(run_record: Mapping[str, object]) -> None:
    run_id = run_record.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("Run Record run_id is missing or invalid")
    if run_record.get("managed") is not False:
        raise ValueError("Run Record managed flag disagrees with explicit gate output")
    phase = run_record.get("phase")
    if not isinstance(phase, str) or not phase:
        raise ValueError("Run Record phase is missing or invalid")
    started_at = _run_timestamp(run_record.get("started_at"), name="started_at")
    updated_at = _run_timestamp(run_record.get("updated_at"), name="updated_at")
    finished_at = _run_timestamp(run_record.get("finished_at"), name="finished_at")
    if updated_at != finished_at or started_at > finished_at:
        raise ValueError("Run Record terminal timestamps are incoherent")


def _run_timestamp(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Run Record {name} is missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Run Record {name} is missing or invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Run Record {name} has no timezone")
    return parsed.astimezone(UTC)


def _parse_run_outcome(value: object) -> RunOutcome:
    if not isinstance(value, str):
        raise ValueError("Run Record state is missing or unsupported")
    try:
        return RunOutcome(value)
    except ValueError as error:
        raise ValueError("Run Record state is missing or unsupported") from error


def _validate_outcome_exit(outcome: RunOutcome, runner_exit: int) -> None:
    expected_exit = {RunOutcome.PASSED: 0, RunOutcome.FAILED: 1}.get(outcome)
    if expected_exit is not None and runner_exit != expected_exit:
        raise ValueError(f"{outcome.value} Run Outcome disagrees with exit {runner_exit}")
    if expected_exit is None and runner_exit == 0:
        raise ValueError(f"{outcome.value} Run Outcome disagrees with exit {runner_exit}")


def _expected_scenarios(
    selection: DockerSelection,
    catalog: Mapping[str, TargetSpec],
) -> frozenset[ScenarioExpectation]:
    if isinstance(selection, TargetedDockerSelection):
        if selection.target not in catalog:
            raise ValueError("requested Docker target is absent from the validated package catalog")
        targets = (selection.target,)
        universal: tuple[ScenarioExpectation, ...] = ()
    else:
        targets = tuple(catalog)
        universal = tuple(
            ScenarioExpectation(
                ScenarioIdentity(f"universal-uninstall-{scope.value}", "multiple", scope.value),
                unsupported=False,
            )
            for scope in Scope
        )
    primary = (
        ScenarioExpectation(
            ScenarioIdentity(f"{target}-{scope.value}", target, scope.value),
            unsupported=not catalog[target].supports(scope),
        )
        for target in targets
        for scope in Scope
    )
    return frozenset((*primary, *universal))


def _validated_catalog(repository: Path) -> Mapping[str, TargetSpec]:
    catalog = repository / CATALOG_DIRECTORY
    try:
        candidates = tuple(sorted(catalog.iterdir(), key=lambda path: path.name))
    except OSError as error:
        raise ValueError(f"cannot read authoritative Install Target catalog: {error}") from error
    target_files = tuple(path for path in candidates if path.suffix == ".yaml")
    if not target_files or any(path.is_symlink() or not path.is_file() for path in target_files):
        raise ValueError("authoritative Install Target catalog is missing or invalid")
    try:
        return load_catalog(catalog)
    except SpecError as error:
        raise ValueError(f"authoritative Install Target catalog is invalid: {error}") from error


def _manifest_findings(
    repository: Path,
    bundle: Path,
    selection: DockerSelection,
) -> tuple[ProductFinding, ...]:
    manifest = load_artifact_object(bundle / DIAGNOSTIC_MANIFEST, kind="Diagnostic Manifest")
    package_targets = validated_package_targets(manifest)
    catalog = _validated_catalog(repository)
    if package_targets != tuple(catalog):
        raise ValueError("Diagnostic Manifest package targets disagree with the catalog authority")
    expected_scenarios = _expected_scenarios(selection, catalog)
    return validate_manifest_findings(
        bundle,
        manifest,
        selection.evidence_value(),
        expected_scenarios,
    )


def consume_terminal_evidence(
    repository: Path,
    bundle: Path,
    selection: DockerSelection,
    runner_exit: int,
) -> TerminalEvidence:
    """Load and cross-check terminal evidence from the whole Diagnostic Bundle."""

    run_record = load_artifact_object(bundle / RUN_RECORD, kind="Run Record")
    _validate_run_record_binding(run_record, repository, bundle, selection, runner_exit)
    outcome = _parse_run_outcome(run_record.get("state"))
    _validate_outcome_exit(outcome, runner_exit)
    findings: tuple[ProductFinding, ...] = ()
    if outcome in {RunOutcome.PASSED, RunOutcome.FAILED}:
        findings = _manifest_findings(repository, bundle, selection)
        if outcome is RunOutcome.PASSED and findings:
            raise ValueError("passed Run Outcome disagrees with Product Findings")
        if outcome is RunOutcome.FAILED and not findings:
            raise ValueError("failed Run Outcome has no Product Findings")
    if outcome is RunOutcome.PASSED:
        return PassedEvidence()
    if outcome is RunOutcome.FAILED:
        return FailedEvidence(findings)
    if outcome is RunOutcome.INCOMPLETE:
        return IncompleteEvidence()
    return InterruptedEvidence()
