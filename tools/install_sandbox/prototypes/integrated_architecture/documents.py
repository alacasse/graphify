"""Versioned diagnostic documents for the integrated architecture prototype.

This module owns the two machine-readable diagnostic authorities and their
strict codecs.  It deliberately knows nothing about filesystem persistence or
process execution.  Unknown fields and variants fail closed.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import StrEnum


class DocumentError(ValueError):
    """A machine-readable diagnostic document is malformed or unsupported."""


class RunOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    INTERRUPTED = "interrupted"


class EvidenceKind(StrEnum):
    MANIFEST = "diagnostic_manifest"
    SCENARIO = "scenario_result"
    PURGE = "purge_result"
    COMMAND = "command_fact"
    OBSERVATION = "observation_fact"
    STREAM = "stream"
    HOST_LOG = "host_log"
    OTHER = "other"


class PhaseStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INCOMPLETE = "INCOMPLETE"


class ScenarioStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    UNSUPPORTED = "UNSUPPORTED"
    INCOMPLETE = "INCOMPLETE"


class PurgeStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    INCOMPLETE = "INCOMPLETE"


class TerminationKind(StrEnum):
    EXITED = "EXITED"
    SIGNALLED = "SIGNALLED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    SPAWN_FAILED = "SPAWN_FAILED"


class ObservationKind(StrEnum):
    CONTENT = "CONTENT"
    ABSENT = "ABSENT"
    READ_FAILURE = "READ_FAILURE"


class WitnessKind(StrEnum):
    INSTALLATION = "INSTALLATION"
    STABLE_INSTALLATION = "STABLE_INSTALLATION"


@dataclass(frozen=True)
class SchemaFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class BindingFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class ReferenceFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class CoherenceFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class PlanCoverageFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class CaptureFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class ObservationFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class PersistenceFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class ReportFailure:
    stage: str
    path: str
    message: str


@dataclass(frozen=True)
class InvalidExitFailure:
    stage: str
    path: str
    message: str
    observed_exit: int


type DiagnosticFailure = (
    SchemaFailure
    | BindingFailure
    | ReferenceFailure
    | CoherenceFailure
    | PlanCoverageFailure
    | CaptureFailure
    | ObservationFailure
    | PersistenceFailure
    | ReportFailure
    | InvalidExitFailure
)


@dataclass(frozen=True)
class EvidenceReference:
    path: str
    kind: EvidenceKind
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class FindingDocument:
    action_id: str
    summary: str
    witness_kind: WitnessKind | None
    witness_identity: str | None


@dataclass(frozen=True)
class PhaseDocument:
    name: str
    status: PhaseStatus
    evidence_actions: tuple[str, ...] = ()
    blocked_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ScenarioDocument:
    name: str
    status: ScenarioStatus
    phases: tuple[PhaseDocument, ...]
    findings: tuple[FindingDocument, ...]
    failures: tuple[str, ...]
    limitations: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class PurgeDocument:
    status: PurgeStatus
    findings: tuple[FindingDocument, ...]
    failures: tuple[str, ...]
    evidence_actions: tuple[str, ...]


@dataclass(frozen=True)
class TerminationDocument:
    kind: TerminationKind
    raw_exit: int | None = None
    signal: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class StreamDocument:
    captured: bytes
    declared_digest: str
    declared_size: int
    capture_error: str | None


@dataclass(frozen=True)
class CommandFactDocument:
    action_id: str
    scenario: str
    phase: str
    purpose: str
    argv: tuple[str, ...]
    cwd: str
    started_ns: int
    finished_ns: int
    termination: TerminationDocument
    reaped: bool
    stdout: StreamDocument
    stderr: StreamDocument
    chronology: tuple[str, ...]


@dataclass(frozen=True)
class ObservationItemDocument:
    rule_key: str
    path: str
    entry_kind: ObservationKind
    byte_size: int | None
    sha256: str | None
    detail: str | None
    semantic_verdict: str | None


@dataclass(frozen=True)
class ObservationFactDocument:
    action_id: str
    scenario: str
    phase: str
    purpose: str
    items: tuple[ObservationItemDocument, ...]
    chronology: tuple[str, ...]


@dataclass(frozen=True)
class UnavailableFactDocument:
    action_id: str
    detail: str
    chronology: tuple[str, ...]


@dataclass(frozen=True)
class ImmutableImageFactDocument:
    action_id: str
    source_revision: str
    immutable_image_identity: str


@dataclass(frozen=True)
class CatalogDocumentsFactDocument:
    action_id: str
    immutable_image_identity: str
    canonical_documents: tuple[str, ...]


@dataclass(frozen=True)
class SubjectPreparedFactDocument:
    action_id: str
    target: str
    scope: str
    prepared_identity: str


@dataclass(frozen=True)
class SubjectProbeFactDocument:
    action_id: str
    target: str
    scope: str
    prepared_identity: str
    package_origin: str
    package_version: str
    interface_available: bool


@dataclass(frozen=True)
class FixturePreparedFactDocument:
    action_id: str
    entries: tuple[tuple[str, str], ...]


type RawFactDocument = (
    CommandFactDocument
    | ObservationFactDocument
    | UnavailableFactDocument
    | ImmutableImageFactDocument
    | CatalogDocumentsFactDocument
    | SubjectPreparedFactDocument
    | SubjectProbeFactDocument
    | FixturePreparedFactDocument
)


@dataclass(frozen=True)
class ManifestProjection:
    passed: int
    findings: int
    unsupported: int
    incomplete: int


@dataclass(frozen=True)
class DiagnosticManifest:
    run_id: str
    selection: str
    image_identity: str
    subject_identity: str
    plan_identity: str
    plan_scenarios: tuple[str, ...]
    purge_required: bool
    scenarios: tuple[ScenarioDocument, ...]
    purge: PurgeDocument
    raw_facts: tuple[RawFactDocument, ...]
    findings: tuple[FindingDocument, ...]
    failures: tuple[DiagnosticFailure, ...]
    runtime_limitations: tuple[str, ...]
    inventory: tuple[EvidenceReference, ...]
    evidence_set_digest: str
    projection: ManifestProjection
    operational_chronology: tuple[str, ...]
    presentation_order: tuple[str, ...]


@dataclass(frozen=True)
class RunningRunRecord:
    run_id: str
    selection: str
    image_identity: str
    subject_identity: str
    phase: str


@dataclass(frozen=True)
class TerminalRunRecord:
    run_id: str
    selection: str
    image_identity: str
    subject_identity: str
    outcome: RunOutcome
    raw_exit: int | None
    invalid_raw_exit: int | None
    interrupt_signal: str | None
    manifest: EvidenceReference | None
    host_log: EvidenceReference
    evidence_set_digest: str | None
    failures: tuple[DiagnosticFailure, ...]


type RunRecord = RunningRunRecord | TerminalRunRecord
type EvidenceDocument = DiagnosticManifest | RunRecord
type JsonValue = None | bool | int | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def encode_document(document: EvidenceDocument) -> bytes:
    """Encode a closed document deterministically."""

    _validate_document(document)
    value = (
        _manifest_value(document)
        if isinstance(document, DiagnosticManifest)
        else _run_value(document)
    )
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def decode_manifest(data: bytes) -> DiagnosticManifest:
    value = _document_object(data)
    _identity(value, "diagnostic_manifest")
    _exact(
        value,
        {
            "kind",
            "version",
            "run_id",
            "selection",
            "image_identity",
            "subject_identity",
            "plan_identity",
            "plan_scenarios",
            "purge_required",
            "scenarios",
            "purge",
            "raw_facts",
            "findings",
            "failures",
            "runtime_limitations",
            "inventory",
            "evidence_set_digest",
            "projection",
            "operational_chronology",
            "presentation_order",
        },
        "manifest",
    )
    result = DiagnosticManifest(
        run_id=_string(value["run_id"], "run_id"),
        selection=_string(value["selection"], "selection"),
        image_identity=_string(value["image_identity"], "image_identity"),
        subject_identity=_string(value["subject_identity"], "subject_identity"),
        plan_identity=_string(value["plan_identity"], "plan_identity"),
        plan_scenarios=_strings(value["plan_scenarios"], "plan_scenarios"),
        purge_required=_boolean(value["purge_required"], "purge_required"),
        scenarios=tuple(_scenario(item) for item in _array(value["scenarios"], "scenarios")),
        purge=_purge(value["purge"]),
        raw_facts=tuple(_raw_fact(item) for item in _array(value["raw_facts"], "raw_facts")),
        findings=tuple(_finding(item) for item in _array(value["findings"], "findings")),
        failures=tuple(_failure(item) for item in _array(value["failures"], "failures")),
        runtime_limitations=_strings(value["runtime_limitations"], "runtime_limitations"),
        inventory=tuple(_reference(item) for item in _array(value["inventory"], "inventory")),
        evidence_set_digest=_digest(value["evidence_set_digest"], "evidence_set_digest"),
        projection=_projection(value["projection"]),
        operational_chronology=_strings(value["operational_chronology"], "operational_chronology"),
        presentation_order=_strings(value["presentation_order"], "presentation_order"),
    )
    _validate_document(result)
    return result


def decode_run_record(data: bytes) -> RunRecord:
    value = _document_object(data)
    _identity(value, "run_record")
    state = _string(value.get("state"), "state")
    common = {
        "run_id": _string(value.get("run_id"), "run_id"),
        "selection": _string(value.get("selection"), "selection"),
        "image_identity": _string(value.get("image_identity"), "image_identity"),
        "subject_identity": _string(value.get("subject_identity"), "subject_identity"),
    }
    if state == "running":
        _exact(
            value,
            {
                "kind",
                "version",
                "state",
                "run_id",
                "selection",
                "image_identity",
                "subject_identity",
                "phase",
            },
            "running run record",
        )
        return RunningRunRecord(**common, phase=_string(value["phase"], "phase"))
    _exact(
        value,
        {
            "kind",
            "version",
            "state",
            "run_id",
            "selection",
            "image_identity",
            "subject_identity",
            "raw_exit",
            "invalid_raw_exit",
            "interrupt_signal",
            "manifest",
            "host_log",
            "evidence_set_digest",
            "failures",
        },
        "terminal run record",
    )
    try:
        outcome = RunOutcome(state)
    except ValueError as exc:
        raise DocumentError(f"unknown run state: {state}") from exc
    result = TerminalRunRecord(
        **common,
        outcome=outcome,
        raw_exit=_optional_integer(value["raw_exit"], "raw_exit"),
        invalid_raw_exit=_optional_integer(value["invalid_raw_exit"], "invalid_raw_exit"),
        interrupt_signal=_optional_string(value["interrupt_signal"], "interrupt_signal"),
        manifest=_optional_reference(value["manifest"]),
        host_log=_reference(value["host_log"]),
        evidence_set_digest=_optional_string(value["evidence_set_digest"], "evidence_set_digest"),
        failures=tuple(_failure(item) for item in _array(value["failures"], "failures")),
    )
    _validate_terminal_record(result)
    return result


def _manifest_value(value: DiagnosticManifest) -> JsonObject:
    return {
        "kind": "diagnostic_manifest",
        "version": 1,
        "run_id": value.run_id,
        "selection": value.selection,
        "image_identity": value.image_identity,
        "subject_identity": value.subject_identity,
        "plan_identity": value.plan_identity,
        "plan_scenarios": list(value.plan_scenarios),
        "purge_required": value.purge_required,
        "scenarios": [_scenario_value(item) for item in value.scenarios],
        "purge": _purge_value(value.purge),
        "raw_facts": [_raw_fact_value(item) for item in value.raw_facts],
        "findings": [_finding_value(item) for item in value.findings],
        "failures": [_failure_value(item) for item in value.failures],
        "runtime_limitations": list(value.runtime_limitations),
        "inventory": [_reference_value(item) for item in value.inventory],
        "evidence_set_digest": value.evidence_set_digest,
        "projection": _projection_value(value.projection),
        "operational_chronology": list(value.operational_chronology),
        "presentation_order": list(value.presentation_order),
    }


def _run_value(value: RunRecord) -> JsonObject:
    result: JsonObject = {
        "kind": "run_record",
        "version": 1,
        "run_id": value.run_id,
        "selection": value.selection,
        "image_identity": value.image_identity,
        "subject_identity": value.subject_identity,
    }
    if isinstance(value, RunningRunRecord):
        result.update({"state": "running", "phase": value.phase})
        return result
    result.update(
        {
            "state": value.outcome.value,
            "raw_exit": value.raw_exit,
            "invalid_raw_exit": value.invalid_raw_exit,
            "interrupt_signal": value.interrupt_signal,
            "manifest": None if value.manifest is None else _reference_value(value.manifest),
            "host_log": _reference_value(value.host_log),
            "evidence_set_digest": value.evidence_set_digest,
            "failures": [_failure_value(item) for item in value.failures],
        }
    )
    return result


def _scenario_value(value: ScenarioDocument) -> JsonObject:
    return {
        "name": value.name,
        "status": value.status.value,
        "phases": [
            {
                "name": item.name,
                "status": item.status.value,
                "evidence_actions": list(item.evidence_actions),
                "blocked_by": item.blocked_by,
                "reason": item.reason,
            }
            for item in value.phases
        ],
        "findings": [_finding_value(item) for item in value.findings],
        "failures": list(value.failures),
        "limitations": list(value.limitations),
        "reason": value.reason,
    }


def _scenario(value: JsonValue) -> ScenarioDocument:
    item = _object(value, "scenario")
    _exact(
        item,
        {"name", "status", "phases", "findings", "failures", "limitations", "reason"},
        "scenario",
    )
    result = ScenarioDocument(
        _string(item["name"], "name"),
        _enum(ScenarioStatus, item["status"], "scenario status"),
        tuple(_phase(part) for part in _array(item["phases"], "phases")),
        tuple(_finding(part) for part in _array(item["findings"], "findings")),
        _strings(item["failures"], "failures"),
        _strings(item["limitations"], "limitations"),
        _optional_string(item["reason"], "reason"),
    )
    _validate_scenario(result)
    return result


def _phase(value: JsonValue) -> PhaseDocument:
    item = _object(value, "phase")
    _exact(
        item,
        {"name", "status", "evidence_actions", "blocked_by", "reason"},
        "phase",
    )
    result = PhaseDocument(
        _string(item["name"], "name"),
        _enum(PhaseStatus, item["status"], "phase status"),
        _strings(item["evidence_actions"], "evidence_actions"),
        _optional_string(item["blocked_by"], "blocked_by"),
        _optional_string(item["reason"], "reason"),
    )
    _validate_phase(result)
    return result


def _purge_value(value: PurgeDocument) -> JsonObject:
    return {
        "status": value.status.value,
        "findings": [_finding_value(item) for item in value.findings],
        "failures": list(value.failures),
        "evidence_actions": list(value.evidence_actions),
    }


def _purge(value: JsonValue) -> PurgeDocument:
    item = _object(value, "purge")
    _exact(item, {"status", "findings", "failures", "evidence_actions"}, "purge")
    result = PurgeDocument(
        _enum(PurgeStatus, item["status"], "purge status"),
        tuple(_finding(part) for part in _array(item["findings"], "findings")),
        _strings(item["failures"], "failures"),
        _strings(item["evidence_actions"], "evidence_actions"),
    )
    _validate_purge(result)
    return result


def _finding_value(value: FindingDocument) -> JsonObject:
    return {
        "action_id": value.action_id,
        "summary": value.summary,
        "witness_kind": None if value.witness_kind is None else value.witness_kind.value,
        "witness_identity": value.witness_identity,
    }


def _finding(value: JsonValue) -> FindingDocument:
    item = _object(value, "finding")
    _exact(item, {"action_id", "summary", "witness_kind", "witness_identity"}, "finding")
    result = FindingDocument(
        _string(item["action_id"], "action_id"),
        _string(item["summary"], "summary"),
        _optional_enum(WitnessKind, item["witness_kind"], "witness_kind"),
        _optional_string(item["witness_identity"], "witness_identity"),
    )
    _validate_finding(result)
    return result


def _raw_fact_value(value: RawFactDocument) -> JsonObject:
    if isinstance(value, CommandFactDocument):
        return {
            "fact": "command",
            "action_id": value.action_id,
            "scenario": value.scenario,
            "phase": value.phase,
            "purpose": value.purpose,
            "argv": list(value.argv),
            "cwd": value.cwd,
            "started_ns": value.started_ns,
            "finished_ns": value.finished_ns,
            "termination": _termination_value(value.termination),
            "reaped": value.reaped,
            "stdout": _stream_value(value.stdout),
            "stderr": _stream_value(value.stderr),
            "chronology": list(value.chronology),
        }
    if isinstance(value, ObservationFactDocument):
        return {
            "fact": "observation",
            "action_id": value.action_id,
            "scenario": value.scenario,
            "phase": value.phase,
            "purpose": value.purpose,
            "items": [_observation_item_value(item) for item in value.items],
            "chronology": list(value.chronology),
        }
    if isinstance(value, ImmutableImageFactDocument):
        return {
            "fact": "immutable_image",
            "action_id": value.action_id,
            "source_revision": value.source_revision,
            "immutable_image_identity": value.immutable_image_identity,
        }
    if isinstance(value, CatalogDocumentsFactDocument):
        return {
            "fact": "catalog_documents",
            "action_id": value.action_id,
            "immutable_image_identity": value.immutable_image_identity,
            "canonical_documents": list(value.canonical_documents),
        }
    if isinstance(value, SubjectPreparedFactDocument):
        return {
            "fact": "subject_prepared",
            "action_id": value.action_id,
            "target": value.target,
            "scope": value.scope,
            "prepared_identity": value.prepared_identity,
        }
    if isinstance(value, SubjectProbeFactDocument):
        return {
            "fact": "subject_probe",
            "action_id": value.action_id,
            "target": value.target,
            "scope": value.scope,
            "prepared_identity": value.prepared_identity,
            "package_origin": value.package_origin,
            "package_version": value.package_version,
            "interface_available": value.interface_available,
        }
    if isinstance(value, FixturePreparedFactDocument):
        return {
            "fact": "fixture_prepared",
            "action_id": value.action_id,
            "entries": [{"path": path, "content": content} for path, content in value.entries],
        }
    return {
        "fact": "unavailable",
        "action_id": value.action_id,
        "detail": value.detail,
        "chronology": list(value.chronology),
    }


def _raw_fact(value: JsonValue) -> RawFactDocument:
    item = _object(value, "raw fact")
    kind = _string(item.get("fact"), "fact")
    if kind == "command":
        return _command_fact(item)
    if kind == "observation":
        return _observation_fact(item)
    return _mechanism_fact(item, kind)


def _command_fact(item: JsonObject) -> CommandFactDocument:
    _exact(
        item,
        {
            "fact",
            "action_id",
            "scenario",
            "phase",
            "purpose",
            "argv",
            "cwd",
            "started_ns",
            "finished_ns",
            "termination",
            "reaped",
            "stdout",
            "stderr",
            "chronology",
        },
        "command fact",
    )
    return CommandFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["scenario"], "scenario"),
        _string(item["phase"], "phase"),
        _string(item["purpose"], "purpose"),
        _strings(item["argv"], "argv"),
        _string(item["cwd"], "cwd"),
        _integer(item["started_ns"], "started_ns"),
        _integer(item["finished_ns"], "finished_ns"),
        _termination(item["termination"]),
        _boolean(item["reaped"], "reaped"),
        _stream(item["stdout"]),
        _stream(item["stderr"]),
        _strings(item["chronology"], "chronology"),
    )


def _observation_fact(item: JsonObject) -> ObservationFactDocument:
    _exact(
        item,
        {"fact", "action_id", "scenario", "phase", "purpose", "items", "chronology"},
        "observation fact",
    )
    return ObservationFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["scenario"], "scenario"),
        _string(item["phase"], "phase"),
        _string(item["purpose"], "purpose"),
        tuple(_observation_item(part) for part in _array(item["items"], "items")),
        _strings(item["chronology"], "chronology"),
    )


def _mechanism_fact(item: JsonObject, kind: str) -> RawFactDocument:
    if kind == "immutable_image":
        return _immutable_image_fact(item)
    if kind == "catalog_documents":
        return _catalog_documents_fact(item)
    if kind == "subject_prepared":
        return _subject_prepared_fact(item)
    if kind == "subject_probe":
        return _subject_probe_fact(item)
    if kind == "fixture_prepared":
        return _fixture_prepared_fact(item)
    if kind == "unavailable":
        return _unavailable_fact(item)
    raise DocumentError(f"unknown raw fact variant: {kind}")


def _immutable_image_fact(item: JsonObject) -> ImmutableImageFactDocument:
    _exact(
        item,
        {"fact", "action_id", "source_revision", "immutable_image_identity"},
        "immutable image fact",
    )
    return ImmutableImageFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["source_revision"], "source_revision"),
        _string(item["immutable_image_identity"], "immutable_image_identity"),
    )


def _catalog_documents_fact(item: JsonObject) -> CatalogDocumentsFactDocument:
    _exact(
        item,
        {"fact", "action_id", "immutable_image_identity", "canonical_documents"},
        "catalog documents fact",
    )
    documents = _strings(item["canonical_documents"], "canonical_documents")
    for document in documents:
        _require_canonical_catalog_document(document)
    return CatalogDocumentsFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["immutable_image_identity"], "immutable_image_identity"),
        documents,
    )


def _require_canonical_catalog_document(document: str) -> None:
    try:
        decoded = json.loads(document)
    except json.JSONDecodeError as exc:
        raise DocumentError("canonical catalog document is invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise DocumentError("canonical catalog document must be an object")
    if json.dumps(decoded, separators=(",", ":"), sort_keys=True) != document:
        raise DocumentError("catalog document is not in canonical form")


def _subject_prepared_fact(item: JsonObject) -> SubjectPreparedFactDocument:
    _exact(
        item,
        {"fact", "action_id", "target", "scope", "prepared_identity"},
        "subject prepared fact",
    )
    return SubjectPreparedFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["target"], "target"),
        _string(item["scope"], "scope"),
        _string(item["prepared_identity"], "prepared_identity"),
    )


def _subject_probe_fact(item: JsonObject) -> SubjectProbeFactDocument:
    _exact(
        item,
        {
            "fact",
            "action_id",
            "target",
            "scope",
            "prepared_identity",
            "package_origin",
            "package_version",
            "interface_available",
        },
        "subject probe fact",
    )
    return SubjectProbeFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["target"], "target"),
        _string(item["scope"], "scope"),
        _string(item["prepared_identity"], "prepared_identity"),
        _string(item["package_origin"], "package_origin"),
        _string(item["package_version"], "package_version"),
        _boolean(item["interface_available"], "interface_available"),
    )


def _fixture_prepared_fact(item: JsonObject) -> FixturePreparedFactDocument:
    _exact(item, {"fact", "action_id", "entries"}, "fixture prepared fact")
    entries = tuple(_fixture_entry(part) for part in _array(item["entries"], "entries"))
    return FixturePreparedFactDocument(_string(item["action_id"], "action_id"), entries)


def _fixture_entry(value: JsonValue) -> tuple[str, str]:
    entry = _object(value, "fixture entry")
    _exact(entry, {"path", "content"}, "fixture entry")
    return _string(entry["path"], "path"), _string(entry["content"], "content")


def _unavailable_fact(item: JsonObject) -> UnavailableFactDocument:
    _exact(item, {"fact", "action_id", "detail", "chronology"}, "unavailable fact")
    return UnavailableFactDocument(
        _string(item["action_id"], "action_id"),
        _string(item["detail"], "detail"),
        _strings(item["chronology"], "chronology"),
    )


def _termination_value(value: TerminationDocument) -> JsonObject:
    return {
        "kind": value.kind.value,
        "raw_exit": value.raw_exit,
        "signal": value.signal,
        "detail": value.detail,
    }


def _termination(value: JsonValue) -> TerminationDocument:
    item = _object(value, "termination")
    _exact(item, {"kind", "raw_exit", "signal", "detail"}, "termination")
    result = TerminationDocument(
        _enum(TerminationKind, item["kind"], "termination kind"),
        _optional_integer(item["raw_exit"], "raw_exit"),
        _optional_string(item["signal"], "signal"),
        _optional_string(item["detail"], "detail"),
    )
    _validate_termination(result)
    return result


def _stream_value(value: StreamDocument) -> JsonObject:
    return {
        "captured_base64": base64.b64encode(value.captured).decode("ascii"),
        "declared_digest": value.declared_digest,
        "declared_size": value.declared_size,
        "capture_error": value.capture_error,
    }


def _stream(value: JsonValue) -> StreamDocument:
    item = _object(value, "stream")
    _exact(
        item,
        {"captured_base64", "declared_digest", "declared_size", "capture_error"},
        "stream",
    )
    encoded = _possibly_empty_string(item["captured_base64"], "captured_base64")
    try:
        captured = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise DocumentError("captured_base64 is invalid") from exc
    return StreamDocument(
        captured,
        _digest(item["declared_digest"], "declared_digest"),
        _integer(item["declared_size"], "declared_size"),
        _optional_string(item["capture_error"], "capture_error"),
    )


def _observation_item_value(value: ObservationItemDocument) -> JsonObject:
    return {
        "rule_key": value.rule_key,
        "path": value.path,
        "entry_kind": value.entry_kind.value,
        "byte_size": value.byte_size,
        "sha256": value.sha256,
        "detail": value.detail,
        "semantic_verdict": value.semantic_verdict,
    }


def _observation_item(value: JsonValue) -> ObservationItemDocument:
    item = _object(value, "observation item")
    _exact(
        item,
        {
            "rule_key",
            "path",
            "entry_kind",
            "byte_size",
            "sha256",
            "detail",
            "semantic_verdict",
        },
        "observation item",
    )
    result = ObservationItemDocument(
        _string(item["rule_key"], "rule_key"),
        _string(item["path"], "path"),
        _enum(ObservationKind, item["entry_kind"], "observation kind"),
        _optional_integer(item["byte_size"], "byte_size"),
        _optional_string(item["sha256"], "sha256"),
        _optional_string(item["detail"], "detail"),
        _optional_string(item["semantic_verdict"], "semantic_verdict"),
    )
    _validate_observation(result)
    return result


def _failure_kind(value: DiagnosticFailure) -> str:
    if isinstance(value, SchemaFailure):
        return "schema"
    if isinstance(value, BindingFailure):
        return "binding"
    if isinstance(value, ReferenceFailure):
        return "reference"
    if isinstance(value, CoherenceFailure):
        return "coherence"
    if isinstance(value, PlanCoverageFailure):
        return "plan_coverage"
    return _secondary_failure_kind(value)


def _secondary_failure_kind(value: DiagnosticFailure) -> str:
    if isinstance(value, CaptureFailure):
        return "capture"
    if isinstance(value, ObservationFailure):
        return "observation"
    if isinstance(value, PersistenceFailure):
        return "persistence"
    if isinstance(value, ReportFailure):
        return "report"
    return "invalid_exit"


def _validate_document(value: EvidenceDocument) -> None:
    if isinstance(value, DiagnosticManifest):
        _validate_manifest(value)
        return
    if isinstance(value, RunningRunRecord):
        if not value.phase:
            raise DocumentError("running phase must be non-empty")
        return
    _validate_terminal_record(value)


def _validate_manifest(value: DiagnosticManifest) -> None:
    for scenario in value.scenarios:
        _validate_scenario(scenario)
    _validate_purge(value.purge)
    for finding in value.findings:
        _validate_finding(finding)
    for fact in value.raw_facts:
        _validate_manifest_fact(fact)


def _validate_manifest_fact(value: RawFactDocument) -> None:
    _validate_raw_fact(value)
    if isinstance(value, CommandFactDocument):
        _validate_termination(value.termination)
    if isinstance(value, ObservationFactDocument):
        for item in value.items:
            _validate_observation(item)


def _validate_terminal_record(value: TerminalRunRecord) -> None:
    completed = value.outcome in {RunOutcome.PASSED, RunOutcome.FAILED}
    if completed and (value.manifest is None or value.evidence_set_digest is None):
        raise DocumentError("completed run requires bound manifest evidence")
    if value.outcome is RunOutcome.INTERRUPTED and value.interrupt_signal is None:
        raise DocumentError("interrupted run requires an interrupt signal")
    if value.outcome is not RunOutcome.INCOMPLETE and value.invalid_raw_exit is not None:
        raise DocumentError("invalid raw exit is allowed only for incomplete runs")
    if value.outcome in {RunOutcome.PASSED, RunOutcome.FAILED} and value.failures:
        raise DocumentError("completed run cannot contain diagnostic failures")


def _validate_phase(value: PhaseDocument) -> None:
    has_evidence = bool(value.evidence_actions)
    if value.status is PhaseStatus.PASS and (not has_evidence or value.reason or value.blocked_by):
        raise DocumentError("PASS phase requires evidence and no reason or blocker")
    if value.status is PhaseStatus.FINDING and (
        not has_evidence or not value.reason or value.blocked_by
    ):
        raise DocumentError("FINDING phase requires evidence and a reason")
    if value.status is PhaseStatus.BLOCKED and (
        has_evidence or not value.reason or not value.blocked_by
    ):
        raise DocumentError("BLOCKED phase is command-free and requires blocker and reason")
    if value.status is PhaseStatus.NOT_APPLICABLE and (
        has_evidence or not value.reason or value.blocked_by
    ):
        raise DocumentError("NOT_APPLICABLE phase is command-free and requires a reason")
    if value.status is PhaseStatus.INCOMPLETE and (not value.reason or value.blocked_by):
        raise DocumentError("INCOMPLETE phase requires a reason")


def _validate_scenario(value: ScenarioDocument) -> None:
    if value.status is ScenarioStatus.PASS:
        _validate_pass_scenario(value)
    elif value.status is ScenarioStatus.FINDING:
        _validate_finding_scenario(value)
    elif value.status is ScenarioStatus.UNSUPPORTED:
        _validate_unsupported_scenario(value)
    else:
        _validate_incomplete_scenario(value)
    for phase in value.phases:
        _validate_phase(phase)


def _validate_pass_scenario(value: ScenarioDocument) -> None:
    if value.findings or value.failures or value.reason:
        raise DocumentError("PASS scenario cannot contain findings, failures, or reason")
    if any(
        phase.status not in {PhaseStatus.PASS, PhaseStatus.NOT_APPLICABLE} for phase in value.phases
    ):
        raise DocumentError("PASS scenario contradicts phase evidence")


def _validate_finding_scenario(value: ScenarioDocument) -> None:
    if not value.findings or value.failures or value.reason:
        raise DocumentError("FINDING scenario requires findings and no diagnostic failure")
    if any(phase.status is PhaseStatus.INCOMPLETE for phase in value.phases):
        raise DocumentError("FINDING scenario cannot hide incomplete phase evidence")


def _validate_unsupported_scenario(value: ScenarioDocument) -> None:
    if value.phases or value.findings or value.failures or not value.reason:
        raise DocumentError("UNSUPPORTED scenario must be command-free with a reason")


def _validate_incomplete_scenario(value: ScenarioDocument) -> None:
    incomplete_phase = any(phase.status is PhaseStatus.INCOMPLETE for phase in value.phases)
    if not value.failures and not incomplete_phase:
        raise DocumentError("INCOMPLETE scenario requires diagnostic failure evidence")


def _validate_purge(value: PurgeDocument) -> None:
    if value.status is PurgeStatus.PASS and (
        value.findings or value.failures or not value.evidence_actions
    ):
        raise DocumentError("PASS purge requires evidence and no findings or failures")
    if value.status is PurgeStatus.FINDING and (
        not value.findings or value.failures or not value.evidence_actions
    ):
        raise DocumentError("FINDING purge requires findings and no failures")
    if value.status is PurgeStatus.INCOMPLETE and not value.failures:
        raise DocumentError("INCOMPLETE purge requires failures")


def _validate_termination(value: TerminationDocument) -> None:
    if value.kind is TerminationKind.EXITED:
        valid = value.raw_exit is not None and value.signal is None and value.detail is None
    elif value.kind is TerminationKind.SIGNALLED:
        valid = value.raw_exit is None and value.signal is not None and value.detail is None
    else:
        valid = value.raw_exit is None and value.signal is None and value.detail is not None
    if not valid:
        raise DocumentError(f"contradictory {value.kind.value} termination fields")


def _validate_observation(value: ObservationItemDocument) -> None:
    if value.entry_kind is ObservationKind.CONTENT:
        valid = (
            value.byte_size is not None
            and value.byte_size >= 0
            and value.sha256 is not None
            and value.detail is None
            and value.semantic_verdict is not None
        )
    elif value.entry_kind is ObservationKind.ABSENT:
        valid = (
            value.byte_size is None
            and value.sha256 is None
            and value.detail is None
            and value.semantic_verdict is not None
        )
    else:
        valid = (
            value.byte_size is None
            and value.sha256 is None
            and value.detail is not None
            and value.semantic_verdict is None
        )
    if not valid:
        raise DocumentError(f"contradictory {value.entry_kind.value} observation fields")


def _validate_finding(value: FindingDocument) -> None:
    if (value.witness_kind is None) != (value.witness_identity is None):
        raise DocumentError("finding witness kind and identity must appear together")


def _validate_raw_fact(value: RawFactDocument) -> None:
    if not value.action_id:
        raise DocumentError("raw fact action identity must be non-empty")
    if isinstance(value, (CommandFactDocument, ObservationFactDocument)):
        _validate_projected_fact(value)
        return
    if isinstance(value, CatalogDocumentsFactDocument):
        _validate_catalog_fact(value)
    if isinstance(value, FixturePreparedFactDocument):
        _validate_fixture_fact(value)


def _validate_projected_fact(
    value: CommandFactDocument | ObservationFactDocument,
) -> None:
    if not value.scenario or not value.phase or not value.purpose:
        raise DocumentError("action projection fields must be non-empty")


def _validate_catalog_fact(value: CatalogDocumentsFactDocument) -> None:
    if not value.canonical_documents:
        raise DocumentError("catalog fact requires documents")
    for document in value.canonical_documents:
        _require_canonical_catalog_document(document)


def _validate_fixture_fact(value: FixturePreparedFactDocument) -> None:
    paths = tuple(path for path, _ in value.entries)
    if len(set(paths)) != len(paths):
        raise DocumentError("fixture preparation repeats a path")


def _failure_value(value: DiagnosticFailure) -> JsonObject:
    result: JsonObject = {
        "kind": _failure_kind(value),
        "stage": value.stage,
        "path": value.path,
        "message": value.message,
    }
    if isinstance(value, InvalidExitFailure):
        result["observed_exit"] = value.observed_exit
    return result


def _failure(value: JsonValue) -> DiagnosticFailure:
    item = _object(value, "failure")
    kind = _string(item.get("kind"), "kind")
    common_keys = {"kind", "stage", "path", "message"}
    _exact(item, common_keys | ({"observed_exit"} if kind == "invalid_exit" else set()), "failure")
    common = (
        _string(item["stage"], "stage"),
        _string(item["path"], "path"),
        _string(item["message"], "message"),
    )
    if kind == "invalid_exit":
        return InvalidExitFailure(*common, _integer(item["observed_exit"], "observed_exit"))
    classes = {
        "schema": SchemaFailure,
        "binding": BindingFailure,
        "reference": ReferenceFailure,
        "coherence": CoherenceFailure,
        "plan_coverage": PlanCoverageFailure,
        "capture": CaptureFailure,
        "observation": ObservationFailure,
        "persistence": PersistenceFailure,
        "report": ReportFailure,
    }
    failure_type = classes.get(kind)
    if failure_type is None:
        raise DocumentError(f"unknown diagnostic failure variant: {kind}")
    return failure_type(*common)


def _reference_value(value: EvidenceReference) -> JsonObject:
    return {
        "path": value.path,
        "kind": value.kind.value,
        "byte_size": value.byte_size,
        "sha256": value.sha256,
    }


def _reference(value: JsonValue) -> EvidenceReference:
    item = _object(value, "reference")
    _exact(item, {"path", "kind", "byte_size", "sha256"}, "reference")
    try:
        kind = EvidenceKind(_string(item["kind"], "kind"))
    except ValueError as exc:
        raise DocumentError("unknown evidence kind") from exc
    return EvidenceReference(
        _string(item["path"], "path"),
        kind,
        _integer(item["byte_size"], "byte_size"),
        _digest(item["sha256"], "sha256"),
    )


def _optional_reference(value: JsonValue) -> EvidenceReference | None:
    return None if value is None else _reference(value)


def _projection_value(value: ManifestProjection) -> JsonObject:
    return {
        "passed": value.passed,
        "findings": value.findings,
        "unsupported": value.unsupported,
        "incomplete": value.incomplete,
    }


def _projection(value: JsonValue) -> ManifestProjection:
    item = _object(value, "projection")
    _exact(item, {"passed", "findings", "unsupported", "incomplete"}, "projection")
    return ManifestProjection(
        *(_integer(item[key], key) for key in ("passed", "findings", "unsupported", "incomplete"))
    )


def _document_object(data: bytes) -> JsonObject:
    try:
        raw: object = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentError("document is not strict UTF-8 JSON") from exc
    return _json_object(raw, "document")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DocumentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _identity(value: JsonObject, expected: str) -> None:
    if value.get("kind") != expected or value.get("version") != 1:
        raise DocumentError(f"unsupported {expected} schema")


def _exact(value: JsonObject, keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise DocumentError(f"{label} keys differ: expected {sorted(keys)}, got {sorted(value)}")


def _json_object(value: object, field: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DocumentError(f"{field} must be an object")
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return _json_object(value, "nested value")
    raise DocumentError("JSON numbers must be integers and values must be closed JSON types")


def _object(value: JsonValue, field: str) -> JsonObject:
    if not isinstance(value, dict):
        raise DocumentError(f"{field} must be an object")
    return value


def _array(value: JsonValue, field: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise DocumentError(f"{field} must be an array")
    return value


def _string(value: JsonValue | None, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentError(f"{field} must be a non-empty string")
    return value


def _possibly_empty_string(value: JsonValue, field: str) -> str:
    if not isinstance(value, str):
        raise DocumentError(f"{field} must be a string")
    return value


def _optional_string(value: JsonValue, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _enum[EnumT: StrEnum](enum_type: type[EnumT], value: JsonValue, field: str) -> EnumT:
    token = _string(value, field)
    try:
        return enum_type(token)
    except ValueError as exc:
        raise DocumentError(f"unknown {field}: {token}") from exc


def _optional_enum[EnumT: StrEnum](
    enum_type: type[EnumT],
    value: JsonValue,
    field: str,
) -> EnumT | None:
    return None if value is None else _enum(enum_type, value, field)


def _strings(value: JsonValue, field: str) -> tuple[str, ...]:
    return tuple(_string(item, field) for item in _array(value, field))


def _integer(value: JsonValue, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentError(f"{field} must be an integer")
    return value


def _optional_integer(value: JsonValue, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _integers(value: JsonValue, field: str) -> tuple[int, ...]:
    return tuple(_integer(item, field) for item in _array(value, field))


def _boolean(value: JsonValue, field: str) -> bool:
    if not isinstance(value, bool):
        raise DocumentError(f"{field} must be a boolean")
    return value


def _digest(value: JsonValue, field: str) -> str:
    digest = _string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise DocumentError(f"{field} must be a lowercase SHA-256 digest")
    return digest
