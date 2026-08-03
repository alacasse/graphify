"""Pure diagnostic authority for the integrated architecture prototype.

Diagnostics translates domain results and resource facts without reinterpreting
either owner.  It assesses an immutable whole-bundle view, derives one report,
and returns a revision-bound terminal proposal.  Persistence remains in
``bundle`` and the Validation Plan remains in ``model``.
"""

# pyright: strict

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import quote

from .bundle import ArtifactReference, BundleEntry, BundleRevision, CoherentBundleReadView
from .documents import (
    BindingFailure,
    CaptureFailure,
    CoherenceFailure,
    CommandFactDocument,
    DiagnosticFailure,
    DiagnosticManifest,
    DocumentError,
    EvidenceKind,
    EvidenceReference,
    FindingDocument,
    InvalidExitFailure,
    ManifestProjection,
    ObservationFactDocument,
    ObservationFailure,
    ObservationItemDocument,
    PhaseDocument,
    PlanCoverageFailure,
    PurgeDocument,
    ReferenceFailure,
    ReportFailure,
    RunningRunRecord,
    RunOutcome,
    ScenarioDocument,
    SchemaFailure,
    StreamDocument,
    TerminalRunRecord,
    TerminationDocument,
    UnavailableFactDocument,
    decode_manifest,
    decode_run_record,
)
from .model import (
    ActionId,
    AggregateScenarioRecord,
    AggregateUninstallFinding,
    AggregateUninstallIncomplete,
    AggregateUninstallNotApplicable,
    AggregateUninstallPassed,
    ApplicationOutcome,
    Cancelled,
    CapturedStream,
    CommandFact,
    Exited,
    ObservationFact,
    ObservationReadFailure,
    ObservedAbsent,
    ObservedContent,
    PhaseFinding,
    PhaseIncomplete,
    PhasePassed,
    PhaseScenarioRecord,
    PlanProjection,
    PreparationFinding,
    PreparationIncomplete,
    PreparationPassed,
    ProductFinding,
    PurgeFinding,
    PurgeIncomplete,
    PurgePassed,
    RawFact,
    ScenarioFinding,
    ScenarioIncomplete,
    ScenarioPassed,
    ScenarioUnsupported,
    Signalled,
    SpawnFailed,
    StableInstallationEstablished,
    StreamCaptureFailure,
    TimedOut,
    UnsupportedScenarioRecord,
    ValidationIncomplete,
)

RUN_PATH = "run.json"
MANIFEST_PATH = "manifest.json"
REPORT_PATH = "report.md"
HOST_LOG_PATH = "runner.log"


@dataclass(frozen=True)
class ExpectedDiagnostic:
    run_id: str
    selection: str
    image_identity: str
    subject_identity: str
    plan: PlanProjection


@dataclass(frozen=True)
class TerminalFacts:
    raw_exit: int | None
    interrupt_signal: str | None = None
    additional_failures: tuple[DiagnosticFailure, ...] = ()


@dataclass(frozen=True)
class ReportInput:
    outcome: RunOutcome
    raw_exit: int | None
    invalid_raw_exit: int | None
    interrupt_signal: str | None
    scenarios: tuple[ScenarioDocument, ...]
    purge: PurgeDocument | None
    findings: tuple[FindingDocument, ...]
    failures: tuple[DiagnosticFailure, ...]
    runtime_limitations: tuple[str, ...]
    evidence_links: tuple[str, ...]
    operational_chronology: tuple[str, ...]
    presentation_order: tuple[str, ...]


@dataclass(frozen=True)
class RunningAssessment:
    run_record: RunningRunRecord
    revision: BundleRevision


@dataclass(frozen=True)
class ReadyToCommit:
    running_record: RunningRunRecord
    terminal_record: TerminalRunRecord
    report: str
    assessed_revision: BundleRevision
    report_was_present: bool


@dataclass(frozen=True)
class CompletedAssessment:
    run_record: TerminalRunRecord
    manifest: DiagnosticManifest | None
    report: str
    revision: BundleRevision


@dataclass(frozen=True)
class InvalidBundle:
    run_record: RunningRunRecord | TerminalRunRecord | None
    failures: tuple[DiagnosticFailure, ...]
    observed_raw_exit: int | None
    revision: BundleRevision


type BundleAssessment = RunningAssessment | ReadyToCommit | CompletedAssessment | InvalidBundle


class Annotation(StrEnum):
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Published:
    artifact_name: str


@dataclass(frozen=True)
class PublicationFailed:
    reason: str


type PublicationFact = Published | PublicationFailed


@dataclass(frozen=True)
class CIClassificationInput:
    assessment: BundleAssessment
    observed_exit: int | None
    publication: PublicationFact
    preserve_nonzero_exit: bool = True


@dataclass(frozen=True)
class CIDecision:
    annotation: Annotation
    exit_code: int
    reasons: tuple[str, ...]


def make_running_record(expected: ExpectedDiagnostic, phase: str = "allocated") -> RunningRunRecord:
    """Construct the host authority that must precede evidence-producing work."""

    return RunningRunRecord(
        expected.run_id,
        expected.selection,
        expected.image_identity,
        expected.subject_identity,
        phase,
    )


def build_manifest(
    expected: ExpectedDiagnostic,
    outcome: ApplicationOutcome,
    inventory: tuple[ArtifactReference, ...],
) -> DiagnosticManifest:
    """Translate domain authority and raw facts into one diagnostic manifest."""

    scenarios = tuple(_scenario_document(record) for record in outcome.scenario_records)
    raw_facts = tuple(_raw_fact_document(fact) for fact in outcome.raw_facts)
    findings = tuple(_finding_document(finding) for finding in outcome.findings)
    failures = _translation_failures(outcome)
    limitations = tuple(limitation for scenario in scenarios for limitation in scenario.limitations)
    references = tuple(_evidence_reference(item) for item in inventory)
    projection = _projection(scenarios)
    chronology = tuple(_action_identity(action) for action in outcome.chronology)
    return DiagnosticManifest(
        run_id=expected.run_id,
        selection=expected.selection,
        image_identity=expected.image_identity,
        subject_identity=expected.subject_identity,
        plan_identity=expected.plan.plan_id.value,
        plan_scenarios=tuple(item.name for item in expected.plan.scenarios),
        purge_required=expected.plan.purge_required,
        scenarios=scenarios,
        purge=_outcome_purge_document(outcome),
        raw_facts=raw_facts,
        findings=findings,
        failures=failures,
        runtime_limitations=_unique(limitations),
        inventory=references,
        evidence_set_digest=evidence_set_digest(references),
        projection=projection,
        operational_chronology=chronology,
        presentation_order=_presentation_order(scenarios, references),
    )


def assess_bundle(
    view: CoherentBundleReadView,
    expected: ExpectedDiagnostic,
    terminal_facts: TerminalFacts | None = None,
) -> BundleAssessment:
    """Assess one coherent resource view without performing I/O or persistence."""

    failures: list[DiagnosticFailure] = list(_multiplicity_failures(view))
    run_record = _read_run_record(view, failures)
    if run_record is None:
        return InvalidBundle(None, _ordered_failures(failures), None, view.revision)
    failures.extend(_identity_failures(run_record, expected))
    if failures:
        return InvalidBundle(
            run_record, _ordered_failures(failures), _recorded_exit(run_record), view.revision
        )
    if isinstance(run_record, RunningRunRecord):
        if terminal_facts is None:
            return RunningAssessment(run_record, view.revision)
        return _prepare_terminal(view, expected, run_record, terminal_facts)
    return _assess_terminal(view, expected, run_record)


def _prepare_terminal(
    view: CoherentBundleReadView,
    expected: ExpectedDiagnostic,
    running: RunningRunRecord,
    facts: TerminalFacts,
) -> BundleAssessment:
    failures: list[DiagnosticFailure] = list(facts.additional_failures)
    manifest = _read_manifest(view, failures)
    if manifest is not None:
        failures.extend(_manifest_failures(view, expected, manifest))
    raw_exit, invalid_raw_exit = _classify_raw_exit(facts.raw_exit, failures)
    outcome = _compose_outcome(manifest, failures, facts.interrupt_signal)
    raw_exit = _normalize_terminal_exit(outcome, raw_exit, facts.interrupt_signal, failures)
    host_log = _entry_reference(view, HOST_LOG_PATH, EvidenceKind.HOST_LOG, failures)
    manifest_reference = _entry_reference(view, MANIFEST_PATH, EvidenceKind.MANIFEST, failures)
    if manifest is None:
        manifest_reference = None
    failures = list(_ordered_failures(failures))
    outcome = _compose_outcome(manifest, failures, facts.interrupt_signal)
    raw_exit = _normalize_incomplete_exit(outcome, raw_exit)
    if host_log is None:
        host_log = EvidenceReference(HOST_LOG_PATH, EvidenceKind.HOST_LOG, 0, "0" * 64)
    terminal = TerminalRunRecord(
        run_id=expected.run_id,
        selection=expected.selection,
        image_identity=expected.image_identity,
        subject_identity=expected.subject_identity,
        outcome=outcome,
        raw_exit=raw_exit,
        invalid_raw_exit=invalid_raw_exit,
        interrupt_signal=facts.interrupt_signal,
        manifest=manifest_reference,
        host_log=host_log,
        evidence_set_digest=None if manifest is None else manifest.evidence_set_digest,
        failures=tuple(failures),
    )
    report = render_report(_report_input(terminal, manifest))
    report_failure = _report_entry_failure(view, report.encode())
    if report_failure is not None:
        return InvalidBundle(
            running,
            _ordered_failures((*failures, report_failure)),
            raw_exit,
            view.revision,
        )
    return ReadyToCommit(
        running,
        terminal,
        report,
        view.revision,
        bool(_entries(view, REPORT_PATH)),
    )


def _assess_terminal(
    view: CoherentBundleReadView,
    expected: ExpectedDiagnostic,
    record: TerminalRunRecord,
) -> BundleAssessment:
    failures: list[DiagnosticFailure] = list(_terminal_invariant_failures(record))
    manifest = _read_manifest(view, failures)
    if record.manifest is None:
        manifest = None
    elif manifest is not None:
        if record.manifest.kind is not EvidenceKind.MANIFEST:
            failures.append(
                ReferenceFailure("reference", MANIFEST_PATH, "manifest reference has wrong kind")
            )
        failures.extend(_manifest_failures(view, expected, manifest))
        failures.extend(_reference_binding_failures(record.manifest, view, MANIFEST_PATH))
    if record.host_log.kind is not EvidenceKind.HOST_LOG:
        failures.append(
            ReferenceFailure("reference", HOST_LOG_PATH, "host log reference has wrong kind")
        )
    failures.extend(_reference_binding_failures(record.host_log, view, HOST_LOG_PATH))
    expected_outcome = _compose_outcome(
        manifest, [*record.failures, *failures], record.interrupt_signal
    )
    if expected_outcome is not record.outcome:
        failures.append(
            CoherenceFailure(
                "terminal", RUN_PATH, "recorded outcome disagrees with authoritative evidence"
            )
        )
    report = render_report(_report_input(record, manifest))
    report_failure = _report_entry_failure(view, report.encode(), required=True)
    if report_failure is not None:
        failures.append(report_failure)
    if failures:
        return InvalidBundle(
            record, _ordered_failures(failures), _recorded_exit(record), view.revision
        )
    return CompletedAssessment(record, manifest, report, view.revision)


def render_report(value: ReportInput) -> str:
    """Render a deterministic human projection; never classify from this text."""

    raw_exit = value.raw_exit if value.raw_exit is not None else "unavailable"
    lines = [
        "# Integrated diagnostic prototype",
        "",
        f"Run Outcome: `{value.outcome.value}`",
        f"Raw exit: `{raw_exit}`",
    ]
    if value.invalid_raw_exit is not None:
        lines.append(f"Invalid observed exit: `{value.invalid_raw_exit}`")
    if value.interrupt_signal is not None:
        lines.append(f"Interrupt: `{_escape(value.interrupt_signal)}`")
    lines.extend(("", "## Scenarios", ""))
    lines.extend(f"- {_escape(item.name)}: `{_escape(item.status)}`" for item in value.scenarios)
    if value.purge is not None:
        lines.extend(("", "## Purge", "", f"- `{_escape(value.purge.status)}`"))
    _append_findings(lines, value.findings)
    _append_failures(lines, value.failures)
    _append_strings(lines, "Runtime Limitations", value.runtime_limitations)
    _append_strings(lines, "Operational chronology", value.operational_chronology)
    _append_strings(lines, "Canonical presentation order", value.presentation_order)
    safe_links = tuple(path for path in value.evidence_links if _safe_path(path))
    if safe_links:
        lines.extend(("", "## Evidence", ""))
        lines.extend(f"- [{_escape(path)}]({quote(path, safe='/-._~')})" for path in safe_links)
    return "\n".join(lines) + "\n"


def classify_ci(value: CIClassificationInput) -> CIDecision:
    """Classify only reopened terminal evidence after a publication attempt."""

    assessment = value.assessment
    if not isinstance(assessment, CompletedAssessment):
        reasons = (
            *_publication_reasons(value.publication),
            "diagnostic_not_reopened_and_complete",
        )
        return CIDecision(Annotation.ERROR, 2, tuple(reasons))
    record = assessment.run_record
    reasons = (*_publication_reasons(value.publication), *_ci_exit_reasons(value, record))
    if reasons:
        return CIDecision(Annotation.ERROR, _ci_error_exit(value, record), tuple(reasons))
    if record.outcome is RunOutcome.PASSED:
        return CIDecision(Annotation.NOTICE, 0, ("coherent_pass",))
    if record.outcome is RunOutcome.FAILED:
        return CIDecision(Annotation.WARNING, 0, ("coherent_product_findings",))
    return CIDecision(
        Annotation.ERROR,
        _ci_error_exit(value, record),
        (f"terminal_{record.outcome.value}",),
    )


def _publication_reasons(value: PublicationFact) -> tuple[str, ...]:
    if isinstance(value, PublicationFailed):
        return (f"publication_failed:{value.reason}",)
    return ()


def _ci_exit_reasons(
    value: CIClassificationInput,
    record: TerminalRunRecord,
) -> tuple[str, ...]:
    observed = value.observed_exit
    if observed is None:
        return ("missing_observed_exit",)
    if not _valid_raw_exit(observed):
        return (f"invalid_observed_exit:{observed}",)
    if record.raw_exit != observed:
        return (f"recorded_observed_exit_mismatch:{record.raw_exit}:{observed}",)
    return ()


def _scenario_document(record: object) -> ScenarioDocument:
    if isinstance(record, UnsupportedScenarioRecord):
        result = record.result
        return ScenarioDocument(result.name, "unsupported", (), (), (), result.limitations)
    if isinstance(record, PhaseScenarioRecord):
        phases = tuple(_phase_document(item) for item in record.phases) + tuple(
            PhaseDocument(item.phase.value, "blocked", item.missing_witness, item.missing_witness)
            for item in record.blocked
        )
        return _scenario_from_result(record.result, phases)
    if isinstance(record, AggregateScenarioRecord):
        phases = tuple(_preparation_document(item) for item in record.preparations)
        phases += (_aggregate_removal_document(record.removal),)
        return _scenario_from_result(record.result, phases)
    raise TypeError(f"unknown scenario record: {type(record).__name__}")


def _scenario_from_result(result: object, phases: tuple[PhaseDocument, ...]) -> ScenarioDocument:
    if isinstance(result, ScenarioPassed):
        return ScenarioDocument(result.name, "passed", phases, (), (), ())
    if isinstance(result, ScenarioFinding):
        return ScenarioDocument(
            result.name,
            "finding",
            phases,
            tuple(_finding_document(item) for item in result.findings),
            (),
            (),
        )
    if isinstance(result, ScenarioIncomplete):
        return ScenarioDocument(result.name, "incomplete", phases, (), result.reasons, ())
    if isinstance(result, ScenarioUnsupported):
        return ScenarioDocument(result.name, "unsupported", (), (), (), result.limitations)
    raise TypeError(f"unknown scenario result: {type(result).__name__}")


def _phase_document(value: object) -> PhaseDocument:
    if isinstance(value, PhasePassed):
        return PhaseDocument(value.phase.value, "passed")
    if isinstance(value, PhaseFinding):
        return PhaseDocument(value.phase.value, "finding", reason=value.finding.summary)
    if isinstance(value, PhaseIncomplete):
        return PhaseDocument(value.phase.value, "incomplete", reason=value.reason)
    raise TypeError(f"unknown phase result: {type(value).__name__}")


def _preparation_document(value: object) -> PhaseDocument:
    if isinstance(value, PreparationPassed):
        return PhaseDocument(f"aggregate-prepare:{value.target}", "passed")
    if isinstance(value, PreparationFinding):
        return PhaseDocument(
            f"aggregate-prepare:{value.target}", "finding", reason=value.finding.summary
        )
    if isinstance(value, PreparationIncomplete):
        return PhaseDocument(f"aggregate-prepare:{value.target}", "incomplete", reason=value.reason)
    raise TypeError(f"unknown aggregate preparation: {type(value).__name__}")


def _aggregate_removal_document(value: object) -> PhaseDocument:
    if isinstance(value, AggregateUninstallPassed):
        return PhaseDocument("aggregate-uninstall", "passed")
    if isinstance(value, AggregateUninstallFinding):
        return PhaseDocument("aggregate-uninstall", "finding", reason=value.finding.summary)
    if isinstance(value, AggregateUninstallIncomplete):
        return PhaseDocument("aggregate-uninstall", "incomplete", reason=value.reason)
    if isinstance(value, AggregateUninstallNotApplicable):
        return PhaseDocument("aggregate-uninstall", "not_applicable", reason=value.reason)
    raise TypeError(f"unknown aggregate removal: {type(value).__name__}")


def _purge_document(value: object) -> PurgeDocument:
    if isinstance(value, PurgePassed):
        return PurgeDocument("passed", (), ())
    if isinstance(value, PurgeFinding):
        return PurgeDocument("finding", (_finding_document(value.finding),), ())
    if isinstance(value, PurgeIncomplete):
        return PurgeDocument("incomplete", (), (value.reason,))
    raise TypeError(f"unknown purge result: {type(value).__name__}")


def _outcome_purge_document(value: ApplicationOutcome) -> PurgeDocument:
    if isinstance(value, ValidationIncomplete):
        return PurgeDocument("incomplete", (), (value.reason,))
    return _purge_document(value.purge_result)


def _finding_document(value: ProductFinding) -> FindingDocument:
    witness = value.witness
    if witness is None:
        return FindingDocument(_action_identity(value.action_id), value.summary, None, None)
    identity = json.dumps(
        {
            "target": witness.target,
            "scope": witness.scope.value,
            "surfaces": [list(surface) for surface in witness.surfaces],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return FindingDocument(
        _action_identity(value.action_id),
        value.summary,
        "stable_installation"
        if isinstance(witness, StableInstallationEstablished)
        else "installation",
        identity,
    )


def _raw_fact_document(
    value: RawFact,
) -> CommandFactDocument | ObservationFactDocument | UnavailableFactDocument:
    if isinstance(value, CommandFact):
        return CommandFactDocument(
            _action_identity(value.action_id),
            value.argv,
            value.cwd,
            value.started_ns,
            value.finished_ns,
            _termination_document(value.termination),
            value.reaped,
            _stream_document(value.stdout),
            _stream_document(value.stderr),
            value.chronology,
        )
    if isinstance(value, ObservationFact):
        return ObservationFactDocument(
            _action_identity(value.action_id),
            tuple(_observation_document(item) for item in value.items),
            value.chronology,
        )
    return UnavailableFactDocument(
        _action_identity(value.action_id), value.detail, value.chronology
    )


def _termination_document(value: object) -> TerminationDocument:
    if isinstance(value, Exited):
        return TerminationDocument("exited", raw_exit=value.code)
    if isinstance(value, Signalled):
        return TerminationDocument("signalled", signal=str(value.signal))
    if isinstance(value, TimedOut):
        return TerminationDocument("timed_out", detail=f"{value.seconds!r}s")
    if isinstance(value, Cancelled):
        return TerminationDocument("cancelled", detail=value.reason)
    if isinstance(value, SpawnFailed):
        return TerminationDocument("spawn_failed", detail=value.detail)
    raise TypeError(f"unknown command termination: {type(value).__name__}")


def _stream_document(value: CapturedStream | StreamCaptureFailure) -> StreamDocument:
    if isinstance(value, CapturedStream):
        return StreamDocument(value.content, value.digest, value.size, None)
    return StreamDocument(value.partial_content, value.digest, value.size, value.detail)


def _observation_document(value: object) -> ObservationItemDocument:
    if isinstance(value, ObservedContent):
        return ObservationItemDocument(
            value.rule_key,
            value.location,
            "content",
            value.size,
            value.digest,
            None,
            value.content,
        )
    if isinstance(value, ObservedAbsent):
        return ObservationItemDocument(
            value.rule_key, value.location, "absent", None, None, None, None
        )
    if isinstance(value, ObservationReadFailure):
        return ObservationItemDocument(
            value.rule_key,
            value.location,
            "read_failure",
            None,
            None,
            value.detail,
            None,
        )
    raise TypeError(f"unknown observation item: {type(value).__name__}")


def _translation_failures(outcome: ApplicationOutcome) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    if isinstance(outcome, ValidationIncomplete):
        failures.append(CoherenceFailure("domain", MANIFEST_PATH, outcome.reason))
    for fact in outcome.raw_facts:
        failures.extend(_fact_failures(fact))
    for scenario in outcome.scenario_records:
        if isinstance(scenario.result, ScenarioIncomplete):
            failures.extend(
                CoherenceFailure("domain", scenario.result.name, reason)
                for reason in scenario.result.reasons
            )
    if not isinstance(outcome, ValidationIncomplete) and isinstance(
        outcome.purge_result, PurgeIncomplete
    ):
        failures.append(CoherenceFailure("purge", "purge", outcome.purge_result.reason))
    return _ordered_failures(failures)


def _fact_failures(value: RawFact) -> tuple[DiagnosticFailure, ...]:
    if isinstance(value, CommandFact):
        return _command_fact_failures(value)
    if isinstance(value, ObservationFact):
        return _observation_fact_failures(value)
    return (CoherenceFailure("fulfilment", _action_identity(value.action_id), value.detail),)


def _command_fact_failures(value: CommandFact) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    if isinstance(value.termination, Exited) and not _valid_raw_exit(value.termination.code):
        failures.append(
            InvalidExitFailure(
                "command",
                _action_identity(value.action_id),
                "exit outside 0..255",
                value.termination.code,
            )
        )
    for name, stream in (("stdout", value.stdout), ("stderr", value.stderr)):
        captured = stream.content if isinstance(stream, CapturedStream) else stream.partial_content
        metadata_changed = (
            hashlib.sha256(captured).hexdigest() != stream.digest or len(captured) != stream.size
        )
        if metadata_changed:
            failures.append(
                CaptureFailure(
                    "command", _action_identity(value.action_id), f"{name} metadata mismatch"
                )
            )
        if isinstance(stream, StreamCaptureFailure):
            failures.append(
                CaptureFailure(
                    "command", _action_identity(value.action_id), f"{name}: {stream.detail}"
                )
            )
    return tuple(failures)


def _observation_fact_failures(value: ObservationFact) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    for item in value.items:
        if isinstance(item, ObservationReadFailure):
            failures.append(ObservationFailure("observation", item.location, item.detail))
        metadata_changed = isinstance(item, ObservedContent) and (
            hashlib.sha256(item.content).hexdigest() != item.digest
            or len(item.content) != item.size
        )
        if metadata_changed:
            failures.append(
                ObservationFailure("observation", item.location, "content metadata mismatch")
            )
    return tuple(failures)


def _manifest_failures(
    view: CoherentBundleReadView,
    expected: ExpectedDiagnostic,
    manifest: DiagnosticManifest,
) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    expected_identity = (
        expected.run_id,
        expected.selection,
        expected.image_identity,
        expected.subject_identity,
        expected.plan.plan_id.value,
    )
    observed_identity = (
        manifest.run_id,
        manifest.selection,
        manifest.image_identity,
        manifest.subject_identity,
        manifest.plan_identity,
    )
    if observed_identity != expected_identity:
        failures.append(
            BindingFailure(
                "manifest",
                MANIFEST_PATH,
                "run, selection, image, subject, or plan identity mismatch",
            )
        )
    expected_names = tuple(item.name for item in expected.plan.scenarios)
    if manifest.plan_scenarios != expected_names:
        failures.append(
            PlanCoverageFailure("manifest", MANIFEST_PATH, "plan scenario projection mismatch")
        )
    if manifest.purge_required != expected.plan.purge_required:
        failures.append(
            PlanCoverageFailure("manifest", MANIFEST_PATH, "purge applicability mismatch")
        )
    failures.extend(_scenario_coverage_failures(expected.plan, manifest.scenarios))
    failures.extend(_projection_failures(manifest))
    failures.extend(_inventory_failures(view, manifest))
    if tuple(sorted(manifest.operational_chronology)) == manifest.operational_chronology:
        # Lexical sorting is almost certainly not execution ordering; this check
        # intentionally does not reject it. It documents that chronology and
        # presentation are separately preserved and assessed below.
        pass
    if manifest.presentation_order != _presentation_order(manifest.scenarios, manifest.inventory):
        failures.append(
            CoherenceFailure(
                "manifest", MANIFEST_PATH, "canonical presentation projection mismatch"
            )
        )
    return tuple(failures)


def _scenario_coverage_failures(
    plan: PlanProjection,
    scenarios: tuple[ScenarioDocument, ...],
) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    names = tuple(item.name for item in scenarios)
    expected_names = tuple(item.name for item in plan.scenarios)
    if names != expected_names or len(set(names)) != len(names):
        failures.append(
            PlanCoverageFailure("manifest", MANIFEST_PATH, "scenario order or cardinality mismatch")
        )
        return tuple(failures)
    by_name = {item.name: item for item in plan.scenarios}
    for scenario in scenarios:
        expected = by_name[scenario.name]
        expected_phases = tuple(item.value for item in expected.expected_phases)
        actual = tuple(_base_phase_name(item.name) for item in scenario.phases)
        if scenario.status == "unsupported":
            if expected.kind.value != "unsupported" or actual:
                failures.append(
                    PlanCoverageFailure(
                        "scenario", scenario.name, "unsupported scenario contradicts plan"
                    )
                )
            continue
        if actual != expected_phases:
            failures.append(
                PlanCoverageFailure(
                    "scenario", scenario.name, "phase order or cardinality mismatch"
                )
            )
        has_incomplete = any(item.status == "incomplete" for item in scenario.phases)
        has_finding = any(item.status in {"finding", "blocked"} for item in scenario.phases)
        if scenario.status == "passed" and (has_incomplete or has_finding):
            failures.append(
                CoherenceFailure(
                    "scenario", scenario.name, "passed summary contradicts phase evidence"
                )
            )
        if scenario.status == "finding" and has_incomplete:
            failures.append(
                CoherenceFailure(
                    "scenario", scenario.name, "finding summary hides incomplete phase"
                )
            )
    return tuple(failures)


def _projection_failures(manifest: DiagnosticManifest) -> tuple[DiagnosticFailure, ...]:
    expected = _projection(manifest.scenarios)
    if manifest.projection != expected:
        return (CoherenceFailure("manifest", MANIFEST_PATH, "scenario count projection mismatch"),)
    return ()


def _inventory_failures(
    view: CoherentBundleReadView,
    manifest: DiagnosticManifest,
) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    paths = tuple(item.path for item in manifest.inventory)
    if len(set(paths)) != len(paths):
        failures.append(ReferenceFailure("inventory", MANIFEST_PATH, "duplicate inventory path"))
    if evidence_set_digest(manifest.inventory) != manifest.evidence_set_digest:
        failures.append(
            CoherenceFailure("inventory", MANIFEST_PATH, "evidence-set digest mismatch")
        )
    for reference in manifest.inventory:
        if reference.kind is not _evidence_kind(reference.path):
            failures.append(
                ReferenceFailure("inventory", reference.path, "evidence kind disagrees with path")
            )
        failures.extend(_reference_binding_failures(reference, view, reference.path))
    authority_paths = {RUN_PATH, MANIFEST_PATH, REPORT_PATH, HOST_LOG_PATH}
    subordinate = tuple(
        str(item.relative_path)
        for item in view.entries
        if str(item.relative_path) not in authority_paths
    )
    if tuple(sorted(paths)) != tuple(sorted(subordinate)):
        failures.append(
            ReferenceFailure(
                "inventory",
                MANIFEST_PATH,
                "inventory is not the multiplicity-preserving subordinate evidence set",
            )
        )
    return tuple(failures)


def _terminal_invariant_failures(record: TerminalRunRecord) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    if record.raw_exit is not None and not _valid_raw_exit(record.raw_exit):
        failures.append(
            InvalidExitFailure(
                "terminal", RUN_PATH, "authoritative raw exit outside 0..255", record.raw_exit
            )
        )
    if record.invalid_raw_exit is not None and _valid_raw_exit(record.invalid_raw_exit):
        failures.append(
            CoherenceFailure("terminal", RUN_PATH, "valid exit stored as invalid evidence")
        )
    completed_invalid = record.outcome in {RunOutcome.PASSED, RunOutcome.FAILED} and (
        record.raw_exit is None or record.manifest is None or bool(record.failures)
    )
    if completed_invalid:
        failures.append(
            CoherenceFailure(
                "terminal", RUN_PATH, "completed outcome lacks coherent bound evidence"
            )
        )
    if record.outcome is RunOutcome.INTERRUPTED and record.interrupt_signal is None:
        failures.append(CoherenceFailure("terminal", RUN_PATH, "interrupted outcome lacks signal"))
    if record.outcome is not RunOutcome.INCOMPLETE and record.invalid_raw_exit is not None:
        failures.append(
            CoherenceFailure("terminal", RUN_PATH, "invalid exit did not force incomplete")
        )
    failures.extend(_record_exit_pair_failures(record))
    return tuple(failures)


def _record_exit_pair_failures(record: TerminalRunRecord) -> tuple[DiagnosticFailure, ...]:
    expected = _expected_terminal_exit(record.outcome, record.interrupt_signal)
    if record.outcome is RunOutcome.INCOMPLETE:
        if record.raw_exit is None or record.raw_exit == 0:
            return (
                CoherenceFailure(
                    "terminal", RUN_PATH, "incomplete outcome requires a nonzero runner exit"
                ),
            )
        return ()
    if expected is not None and record.raw_exit != expected:
        return (
            CoherenceFailure(
                "terminal",
                RUN_PATH,
                f"{record.outcome.value} requires runner exit {expected}",
            ),
        )
    return ()


def _compose_outcome(
    manifest: DiagnosticManifest | None,
    failures: list[DiagnosticFailure] | tuple[DiagnosticFailure, ...],
    interrupt_signal: str | None,
) -> RunOutcome:
    if (
        failures
        or manifest is None
        or manifest.failures
        or manifest.projection.incomplete
        or manifest.purge.status == "incomplete"
    ):
        return RunOutcome.INCOMPLETE
    if interrupt_signal is not None:
        return RunOutcome.INTERRUPTED
    if manifest.findings or manifest.projection.findings or manifest.purge.status == "finding":
        return RunOutcome.FAILED
    return RunOutcome.PASSED


def _read_run_record(
    view: CoherentBundleReadView,
    failures: list[DiagnosticFailure],
) -> RunningRunRecord | TerminalRunRecord | None:
    entry = _entry(view, RUN_PATH, failures)
    if entry is None:
        return None
    try:
        return decode_run_record(entry.content)
    except DocumentError as exc:
        failures.append(SchemaFailure("decode", RUN_PATH, str(exc)))
        return None


def _read_manifest(
    view: CoherentBundleReadView,
    failures: list[DiagnosticFailure],
) -> DiagnosticManifest | None:
    matches = _entries(view, MANIFEST_PATH)
    if not matches:
        return None
    if len(matches) != 1:
        failures.append(
            ReferenceFailure(
                "decode", MANIFEST_PATH, f"expected one manifest, observed {len(matches)}"
            )
        )
        return None
    try:
        return decode_manifest(matches[0].content)
    except DocumentError as exc:
        failures.append(SchemaFailure("decode", MANIFEST_PATH, str(exc)))
        return None


def _identity_failures(
    record: RunningRunRecord | TerminalRunRecord,
    expected: ExpectedDiagnostic,
) -> tuple[DiagnosticFailure, ...]:
    actual = (record.run_id, record.selection, record.image_identity, record.subject_identity)
    wanted = (
        expected.run_id,
        expected.selection,
        expected.image_identity,
        expected.subject_identity,
    )
    if actual != wanted:
        return (
            BindingFailure("run", RUN_PATH, "run, selection, image, or subject identity mismatch"),
        )
    return ()


def _reference_binding_failures(
    reference: EvidenceReference,
    view: CoherentBundleReadView,
    expected_path: str,
) -> tuple[DiagnosticFailure, ...]:
    matches = _entries(view, reference.path)
    if reference.path != expected_path or not _safe_path(reference.path):
        return (
            ReferenceFailure(
                "reference", reference.path, "unsafe or unexpected bundle-relative path"
            ),
        )
    if len(matches) != 1:
        return (
            ReferenceFailure(
                "reference", reference.path, f"expected one regular entry, observed {len(matches)}"
            ),
        )
    entry = matches[0]
    if entry.reference.size != reference.byte_size or entry.reference.sha256 != reference.sha256:
        return (ReferenceFailure("reference", reference.path, "size or digest mismatch"),)
    return ()


def _entry_reference(
    view: CoherentBundleReadView,
    path: str,
    kind: EvidenceKind,
    failures: list[DiagnosticFailure],
) -> EvidenceReference | None:
    entry = _entry(view, path, failures)
    if entry is None:
        return None
    return EvidenceReference(path, kind, entry.reference.size, entry.reference.sha256)


def _entry(
    view: CoherentBundleReadView,
    path: str,
    failures: list[DiagnosticFailure],
) -> BundleEntry | None:
    matches = _entries(view, path)
    if len(matches) != 1:
        failures.append(
            ReferenceFailure("bundle", path, f"expected one regular entry, observed {len(matches)}")
        )
        return None
    return matches[0]


def _entries(view: CoherentBundleReadView, path: str) -> tuple[BundleEntry, ...]:
    selected = PurePosixPath(path)
    return tuple(item for item in view.entries if item.relative_path == selected)


def _multiplicity_failures(view: CoherentBundleReadView) -> tuple[DiagnosticFailure, ...]:
    paths = tuple(str(item.relative_path) for item in view.entries)
    return tuple(
        CoherenceFailure("bundle", path, "duplicate path in coherent view")
        for path in sorted(set(paths))
        if paths.count(path) != 1
    )


def _report_entry_failure(
    view: CoherentBundleReadView,
    expected: bytes,
    *,
    required: bool = False,
) -> ReportFailure | None:
    matches = _entries(view, REPORT_PATH)
    if not matches:
        if required:
            return ReportFailure("report", REPORT_PATH, "report is missing")
        return None
    if len(matches) != 1:
        return ReportFailure("report", REPORT_PATH, "report path is not unique")
    if matches[0].content != expected:
        return ReportFailure("report", REPORT_PATH, "report disagrees with machine authority")
    return None


def _report_input(record: TerminalRunRecord, manifest: DiagnosticManifest | None) -> ReportInput:
    scenarios = () if manifest is None else manifest.scenarios
    purge = None if manifest is None else manifest.purge
    findings = () if manifest is None else manifest.findings
    limitations = () if manifest is None else manifest.runtime_limitations
    chronology = () if manifest is None else manifest.operational_chronology
    presentation = () if manifest is None else manifest.presentation_order
    links = (record.host_log.path,)
    if manifest is not None:
        links += tuple(item.path for item in manifest.inventory)
    return ReportInput(
        record.outcome,
        record.raw_exit,
        record.invalid_raw_exit,
        record.interrupt_signal,
        scenarios,
        purge,
        findings,
        record.failures,
        limitations,
        links,
        chronology,
        presentation,
    )


def _projection(scenarios: tuple[ScenarioDocument, ...]) -> ManifestProjection:
    statuses = tuple(item.status for item in scenarios)
    return ManifestProjection(
        statuses.count("passed"),
        statuses.count("finding"),
        statuses.count("unsupported"),
        statuses.count("incomplete"),
    )


def _presentation_order(
    scenarios: tuple[ScenarioDocument, ...],
    references: tuple[EvidenceReference, ...],
) -> tuple[str, ...]:
    scenario_items = tuple(
        f"scenario:{scenario.name}:{phase.name}:{phase.status}"
        for scenario in scenarios
        for phase in scenario.phases
    )
    evidence_items = tuple(f"evidence:{item.path}:{item.kind.value}" for item in references)
    return tuple(sorted((*scenario_items, *evidence_items)))


def evidence_set_digest(references: tuple[EvidenceReference, ...]) -> str:
    digest = hashlib.sha256()
    for item in sorted(references, key=lambda value: (value.path, value.kind.value)):
        digest.update(f"{item.path}\0{item.kind.value}\0{item.byte_size}\0{item.sha256}\n".encode())
    return digest.hexdigest()


def _evidence_reference(value: ArtifactReference) -> EvidenceReference:
    path = str(value.relative_path)
    kind = _evidence_kind(path)
    return EvidenceReference(path, kind, value.size, value.sha256)


def _evidence_kind(path: str) -> EvidenceKind:
    if "scenario" in path:
        return EvidenceKind.SCENARIO
    if "purge" in path:
        return EvidenceKind.PURGE
    if "stdout" in path or "stderr" in path:
        return EvidenceKind.STREAM
    if "command" in path:
        return EvidenceKind.COMMAND
    if "observation" in path or "snapshot" in path:
        return EvidenceKind.OBSERVATION
    return EvidenceKind.OTHER


def _classify_raw_exit(
    observed: int | None,
    failures: list[DiagnosticFailure],
) -> tuple[int, int | None]:
    if observed is None:
        failures.append(InvalidExitFailure("terminal", RUN_PATH, "raw exit is missing", -1))
        return 2, None
    if not _valid_raw_exit(observed):
        failures.append(
            InvalidExitFailure("terminal", RUN_PATH, "raw exit outside 0..255", observed)
        )
        return 2, observed
    return observed, None


def _normalize_terminal_exit(
    outcome: RunOutcome,
    raw_exit: int,
    signal: str | None,
    failures: list[DiagnosticFailure],
) -> int:
    expected = _expected_terminal_exit(outcome, signal)
    if outcome is RunOutcome.INCOMPLETE:
        return 2 if raw_exit == 0 else raw_exit
    if expected is None:
        failures.append(
            CoherenceFailure("terminal", RUN_PATH, "interrupt signal has no conventional exit")
        )
        return 2 if raw_exit == 0 else raw_exit
    if raw_exit != expected:
        failures.append(
            CoherenceFailure(
                "terminal", RUN_PATH, f"{outcome.value} requires runner exit {expected}"
            )
        )
    return raw_exit


def _normalize_incomplete_exit(outcome: RunOutcome, raw_exit: int) -> int:
    return 2 if outcome is RunOutcome.INCOMPLETE and raw_exit == 0 else raw_exit


def _expected_terminal_exit(outcome: RunOutcome, signal: str | None) -> int | None:
    if outcome is RunOutcome.PASSED:
        return 0
    if outcome is RunOutcome.FAILED:
        return 1
    if outcome is not RunOutcome.INTERRUPTED:
        return None
    normalized = "" if signal is None else signal.upper()
    if normalized in {"SIGINT", "INT", "2"}:
        return 130
    if normalized in {"SIGTERM", "TERM", "15"}:
        return 143
    return None


def _valid_raw_exit(value: int) -> bool:
    return not isinstance(value, bool) and 0 <= value <= 255


def _recorded_exit(record: RunningRunRecord | TerminalRunRecord) -> int | None:
    return None if isinstance(record, RunningRunRecord) else record.raw_exit


def _ci_error_exit(value: CIClassificationInput, record: TerminalRunRecord) -> int:
    if not value.preserve_nonzero_exit:
        return 2
    observed = value.observed_exit
    if observed is not None and _valid_raw_exit(observed) and observed > 0:
        return observed
    if record.raw_exit is not None and record.raw_exit > 0:
        return record.raw_exit
    return 2


def _action_identity(value: ActionId) -> str:
    return f"{value.run_id.value}:{value.plan_id.value}:{value.ordinal}"


def _base_phase_name(name: str) -> str:
    return name.partition(":")[0]


def _safe_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return (
        bool(path)
        and not candidate.is_absolute()
        and all(part not in {"", ".", ".."} for part in candidate.parts)
    )


def _ordered_failures(
    values: list[DiagnosticFailure] | tuple[DiagnosticFailure, ...],
) -> tuple[DiagnosticFailure, ...]:
    return tuple(
        sorted(values, key=lambda item: (_failure_name(item), item.stage, item.path, item.message))
    )


def _failure_name(value: DiagnosticFailure) -> str:
    return type(value).__name__


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _escape(value: str) -> str:
    return re.sub(r"([\\`*_[\]<>#])", r"\\\1", value.replace("\r", " ").replace("\n", " "))


def _append_findings(lines: list[str], values: tuple[FindingDocument, ...]) -> None:
    if values:
        lines.extend(("", "## Product Findings", ""))
        lines.extend(f"- {_escape(item.summary)} ({_escape(item.action_id)})" for item in values)


def _append_failures(lines: list[str], values: tuple[DiagnosticFailure, ...]) -> None:
    if values:
        lines.extend(("", "## Diagnostic Failures", ""))
        lines.extend(_failure_report_line(item) for item in values)


def _failure_report_line(value: DiagnosticFailure) -> str:
    return (
        f"- {_escape(_failure_name(value))} at {_escape(value.stage)} "
        f"[{_escape(value.path)}]: {_escape(value.message)}"
    )


def _append_strings(lines: list[str], heading: str, values: tuple[str, ...]) -> None:
    if values:
        lines.extend(("", f"## {heading}", ""))
        lines.extend(f"- {_escape(item)}" for item in values)
