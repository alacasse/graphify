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
    witness_kind: str | None
    witness_identity: str | None


@dataclass(frozen=True)
class PhaseDocument:
    name: str
    status: str
    blocked_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ScenarioDocument:
    name: str
    status: str
    phases: tuple[PhaseDocument, ...]
    findings: tuple[FindingDocument, ...]
    failures: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PurgeDocument:
    status: str
    findings: tuple[FindingDocument, ...]
    failures: tuple[str, ...]


@dataclass(frozen=True)
class TerminationDocument:
    kind: str
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
    entry_kind: str
    byte_size: int | None
    sha256: str | None
    detail: str | None
    content: bytes | None


@dataclass(frozen=True)
class ObservationFactDocument:
    action_id: str
    items: tuple[ObservationItemDocument, ...]
    chronology: tuple[str, ...]


@dataclass(frozen=True)
class UnavailableFactDocument:
    action_id: str
    detail: str
    chronology: tuple[str, ...]


type RawFactDocument = CommandFactDocument | ObservationFactDocument | UnavailableFactDocument


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
    return DiagnosticManifest(
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
    return TerminalRunRecord(
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
        "status": value.status,
        "phases": [
            {
                "name": item.name,
                "status": item.status,
                "blocked_by": item.blocked_by,
                "reason": item.reason,
            }
            for item in value.phases
        ],
        "findings": [_finding_value(item) for item in value.findings],
        "failures": list(value.failures),
        "limitations": list(value.limitations),
    }


def _scenario(value: JsonValue) -> ScenarioDocument:
    item = _object(value, "scenario")
    _exact(item, {"name", "status", "phases", "findings", "failures", "limitations"}, "scenario")
    return ScenarioDocument(
        _string(item["name"], "name"),
        _string(item["status"], "status"),
        tuple(_phase(part) for part in _array(item["phases"], "phases")),
        tuple(_finding(part) for part in _array(item["findings"], "findings")),
        _strings(item["failures"], "failures"),
        _strings(item["limitations"], "limitations"),
    )


def _phase(value: JsonValue) -> PhaseDocument:
    item = _object(value, "phase")
    _exact(item, {"name", "status", "blocked_by", "reason"}, "phase")
    return PhaseDocument(
        _string(item["name"], "name"),
        _string(item["status"], "status"),
        _optional_string(item["blocked_by"], "blocked_by"),
        _optional_string(item["reason"], "reason"),
    )


def _purge_value(value: PurgeDocument) -> JsonObject:
    return {
        "status": value.status,
        "findings": [_finding_value(item) for item in value.findings],
        "failures": list(value.failures),
    }


def _purge(value: JsonValue) -> PurgeDocument:
    item = _object(value, "purge")
    _exact(item, {"status", "findings", "failures"}, "purge")
    return PurgeDocument(
        _string(item["status"], "status"),
        tuple(_finding(part) for part in _array(item["findings"], "findings")),
        _strings(item["failures"], "failures"),
    )


def _finding_value(value: FindingDocument) -> JsonObject:
    return {
        "action_id": value.action_id,
        "summary": value.summary,
        "witness_kind": value.witness_kind,
        "witness_identity": value.witness_identity,
    }


def _finding(value: JsonValue) -> FindingDocument:
    item = _object(value, "finding")
    _exact(item, {"action_id", "summary", "witness_kind", "witness_identity"}, "finding")
    return FindingDocument(
        _string(item["action_id"], "action_id"),
        _string(item["summary"], "summary"),
        _optional_string(item["witness_kind"], "witness_kind"),
        _optional_string(item["witness_identity"], "witness_identity"),
    )


def _raw_fact_value(value: RawFactDocument) -> JsonObject:
    if isinstance(value, CommandFactDocument):
        return {
            "fact": "command",
            "action_id": value.action_id,
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
            "items": [_observation_item_value(item) for item in value.items],
            "chronology": list(value.chronology),
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
        _exact(
            item,
            {
                "fact",
                "action_id",
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
    if kind == "observation":
        _exact(item, {"fact", "action_id", "items", "chronology"}, "observation fact")
        return ObservationFactDocument(
            _string(item["action_id"], "action_id"),
            tuple(_observation_item(part) for part in _array(item["items"], "items")),
            _strings(item["chronology"], "chronology"),
        )
    if kind == "unavailable":
        _exact(item, {"fact", "action_id", "detail", "chronology"}, "unavailable fact")
        return UnavailableFactDocument(
            _string(item["action_id"], "action_id"),
            _string(item["detail"], "detail"),
            _strings(item["chronology"], "chronology"),
        )
    raise DocumentError(f"unknown raw fact variant: {kind}")


def _termination_value(value: TerminationDocument) -> JsonObject:
    return {
        "kind": value.kind,
        "raw_exit": value.raw_exit,
        "signal": value.signal,
        "detail": value.detail,
    }


def _termination(value: JsonValue) -> TerminationDocument:
    item = _object(value, "termination")
    _exact(item, {"kind", "raw_exit", "signal", "detail"}, "termination")
    return TerminationDocument(
        _string(item["kind"], "kind"),
        _optional_integer(item["raw_exit"], "raw_exit"),
        _optional_string(item["signal"], "signal"),
        _optional_string(item["detail"], "detail"),
    )


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
        "entry_kind": value.entry_kind,
        "byte_size": value.byte_size,
        "sha256": value.sha256,
        "detail": value.detail,
        "content_base64": None
        if value.content is None
        else base64.b64encode(value.content).decode("ascii"),
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
            "content_base64",
        },
        "observation item",
    )
    encoded = _optional_string(item["content_base64"], "content_base64")
    try:
        content = None if encoded is None else base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise DocumentError("content_base64 is invalid") from exc
    return ObservationItemDocument(
        _string(item["rule_key"], "rule_key"),
        _string(item["path"], "path"),
        _string(item["entry_kind"], "entry_kind"),
        _optional_integer(item["byte_size"], "byte_size"),
        _optional_string(item["sha256"], "sha256"),
        _optional_string(item["detail"], "detail"),
        content,
    )


def _failure_kind(value: DiagnosticFailure) -> str:
    return {
        SchemaFailure: "schema",
        BindingFailure: "binding",
        ReferenceFailure: "reference",
        CoherenceFailure: "coherence",
        PlanCoverageFailure: "plan_coverage",
        CaptureFailure: "capture",
        ObservationFailure: "observation",
        PersistenceFailure: "persistence",
        ReportFailure: "report",
        InvalidExitFailure: "invalid_exit",
    }[type(value)]


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
