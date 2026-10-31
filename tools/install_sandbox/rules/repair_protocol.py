"""Closed, effect-free protocol for retained Markdown preparation evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import PurePosixPath
from typing import Literal

from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot, same_observation
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    IntermediateEvidence,
    StepEvidence,
    VerificationResult,
)
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import preservation_baseline
from tools.install_sandbox.rules.repair_scenario import MarkdownRepairScenario, PreparationBlocked

ARTIFACTS = (
    ("operation", "intermediate/operation.json", "operation_retained"),
    (
        "preparation_expectations",
        "expectations/intermediate.json",
        "preparation_expectations_retained",
    ),
    ("repair_plan", "intermediate/repair-plan.json", "repair_plan_retained"),
    ("before", "intermediate/before.json", "before_retained"),
    ("performed", "intermediate/performed.json", "mutation_recorded"),
    ("after", "intermediate/after.json", "after_retained"),
    ("verification", "intermediate/verification.json", "verification_retained"),
    ("effective_expectations", "expectations/reinstall.json", "ready"),
)
STAGES = ("not_started", "started", *(item[2] for item in ARTIFACTS))


def _data(value: object) -> object:
    if isinstance(value, FilesystemSnapshot):
        entries = [
            {k: v for k, v in item.items() if k not in {"content_file", "sha256"}}
            for item in value.entries
        ]
        return {
            "entries": sorted(entries, key=lambda item: (item["root"], item["path"])),
            "contents": [[*key, content.hex()] for key, content in sorted(value.contents.items())],
            "obstacles": copy.deepcopy(value.obstacles),
        }
    if isinstance(value, (BoundMarkdownMutation, PerformedMutation, ExpectationSet)):
        return value.to_data()
    if isinstance(value, VerificationResult):
        return asdict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def artifact_digest(payload: object) -> str:
    """Hash logical content, independently of snapshot blob locations."""
    encoded = json.dumps(_data(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _conforming(verdict: VerificationResult) -> bool:
    return verdict.complete and not verdict.mismatches and not verdict.obstacles


@dataclass(frozen=True)
class RepairInputs:
    case_bytes: bytes
    sources: FilesystemSnapshot
    installed: ExpectationSet
    first_after: FilesystemSnapshot
    first_step: StepEvidence


@dataclass(frozen=True)
class PendingCheckpoint:
    checkpoint: IntermediateEvidence
    session_id: str
    generation: int
    sha256: str


@dataclass(frozen=True)
class Action:
    kind: str
    reference: str
    payload: object
    generation: int


@dataclass(frozen=True)
class Ready:
    expectations: ExpectationSet
    baseline: FilesystemSnapshot


@dataclass(frozen=True)
class Stop:
    reason: str
    diagnostic: Literal["failed", "incomplete"] = "incomplete"


@dataclass(frozen=True)
class Inspection:
    published: str
    present: str
    diagnostic: Literal["passed", "failed", "incomplete"]
    ready: Ready | None


class RepairSession:
    """Detached facts are private; every returned value is a detached copy."""

    def __init__(self, inputs: RepairInputs) -> None:
        self._inputs = copy.deepcopy(inputs)
        self.session_id = uuid.uuid4().hex
        self._index = -1
        self._payloads: dict[str, object] = {}
        self._reason: str | None = None
        self._pending: PendingCheckpoint | None = None
        self._checkpoint: IntermediateEvidence = {
            "stage": "not_started",
            "generation": 0,
            "reason": None,
        }
        first = self._inputs.first_step
        command = first["command"]
        verdict = first["verification"]
        self._blocked: str | None = None
        if (
            first["progress"] != "finished"
            or command is None
            or command["state"] != "completed"
            or command["exit_code"] != 0
            or verdict is None
            or not _conforming(verdict)
        ):
            self._blocked = "First installation not completed and conforming"
            self._plan = None
            return
        case = EffectInstallCase.from_json(inputs.case_bytes.decode("utf-8"))
        plan = MarkdownRepairScenario.from_case(case, self._inputs.sources).bind(
            self._inputs.first_after,
            "steps/0/after.json",
            verdict,
            self._inputs.installed,
            self._inputs.case_bytes,
        )
        if isinstance(plan, PreparationBlocked):
            self._blocked = plan.reason
            self._plan = None
            return
        self._plan = plan
        self._make_pending("started", 1)

    @property
    def blocked_reason(self) -> str | None:
        return self._blocked

    @property
    def pending(self) -> PendingCheckpoint | None:
        return copy.deepcopy(self._pending)

    @property
    def checkpoint(self) -> IntermediateEvidence:
        return copy.deepcopy(self._checkpoint)

    def _make_pending(self, stage: str, generation: int) -> PendingCheckpoint:
        checkpoint: IntermediateEvidence = {
            "stage": stage,
            "generation": generation,
            "reason": self._reason,
        }
        self._pending = PendingCheckpoint(
            checkpoint, self.session_id, generation, artifact_digest(checkpoint)
        )
        return copy.deepcopy(self._pending)

    def confirm_checkpoint(self, receipt: CheckpointReceipt) -> None:
        pending = self._pending
        if pending is None or (
            receipt.session_id != pending.session_id
            or receipt.generation != pending.generation
            or receipt.sha256 != pending.sha256
        ):
            raise ValueError("Checkpoint acknowledgement does not match pending publication")
        self._checkpoint = copy.deepcopy(pending.checkpoint)
        self._pending = None

    def next_action(self) -> Action | Ready | Stop:
        if self._pending is not None:
            raise ValueError("Pending checkpoint publication blocks dependent actions")
        if self._blocked is not None or self._reason is not None:
            verdict = self._payloads.get("verification")
            failed = (
                isinstance(verdict, VerificationResult)
                and verdict.complete
                and bool(verdict.mismatches)
            )
            return Stop(
                self._blocked or self._reason or "Stopped",
                "failed" if failed else "incomplete",
            )
        assert self._plan is not None
        if self._index == len(ARTIFACTS) - 1:
            return Ready(copy.deepcopy(self._effective()), copy.deepcopy(self._after()))
        kind, reference, _ = ARTIFACTS[self._index + 1]
        return Action(
            kind,
            reference,
            copy.deepcopy(self._action_payload(kind)),
            self._checkpoint["generation"] + 1,
        )

    def _action_payload(self, kind: str) -> object:
        assert self._plan is not None
        match kind:
            case "operation":
                return self._plan.operation
            case "preparation_expectations":
                return self._plan.after_preparation_expectations
            case "repair_plan":
                return self._plan.second_install_expectations
            case "performed":
                return self._payloads["operation"]
            case "verification":
                return EffectVerifier().verify(
                    self._plan.after_preparation_expectations, self._after()
                )
            case "effective_expectations":
                return self._effective()
            case _:
                return None

    def _after(self) -> FilesystemSnapshot:
        value = self._payloads["after"]
        assert isinstance(value, FilesystemSnapshot)
        return value

    def _effective(self) -> ExpectationSet:
        assert self._plan is not None
        return replace(
            self._plan.second_install_expectations,
            baseline=preservation_baseline(self._after(), "reinstall"),
        )

    def record(
        self, kind: str, payload: object, artifact_receipt: ArtifactReceipt
    ) -> PendingCheckpoint:
        action = self.next_action()
        if not isinstance(action, Action) or action.kind != kind:
            raise ValueError("Artifact does not follow the published prefix")
        if (
            artifact_receipt.reference != action.reference
            or artifact_receipt.sha256 != artifact_digest(payload)
        ):
            raise ValueError("Artifact acknowledgement differs from retained content")
        saved = copy.deepcopy(payload)
        self._validate(kind, saved, action.payload)
        self._payloads[kind] = saved
        self._index += 1
        return self._make_pending(ARTIFACTS[self._index][2], action.generation)

    def _validate(self, kind: str, payload: object, expected: object) -> None:
        if kind in {"operation", "performed"}:
            self._validate_mutation(kind, payload)
        elif kind in {"before", "after"}:
            self._validate_observation(kind, payload)
        elif artifact_digest(payload) != artifact_digest(expected):
            raise ValueError("Evidence contradicts independently reconstructed expectations")
        if kind == "verification":
            if not isinstance(payload, VerificationResult):
                raise ValueError("Expected preparation verdict")
            if not _conforming(payload):
                self._reason = "Preparation verification failed or incomplete"

    def _validate_mutation(self, kind: str, payload: object) -> None:
        assert self._plan is not None
        if kind == "operation":
            if not isinstance(payload, BoundMarkdownMutation):
                raise ValueError("Expected bound mutation")
            if payload.destination != self._plan.operation.destination:
                raise ValueError("Operation destination differs from case")
            payload.verify_binding(self._inputs.case_bytes, self._inputs.first_after)
        elif (
            not isinstance(payload, PerformedMutation)
            or payload.operation != self._payloads["operation"]
        ):
            raise ValueError("Performed mutation contradicts retained operation")

    def _validate_observation(self, kind: str, payload: object) -> None:
        if not isinstance(payload, FilesystemSnapshot):
            raise ValueError("Expected preparation observation")
        _validate_snapshot(payload)
        if kind == "before":
            if not same_observation(self._inputs.first_after, payload):
                self._reason = "Environment changed before mutation or observation obstructed"
            return
        performed = self._payloads["performed"]
        operation = self._payloads["operation"]
        assert isinstance(performed, PerformedMutation)
        assert isinstance(operation, BoundMarkdownMutation)
        performed.verify(operation, payload)


def begin(inputs: RepairInputs) -> RepairSession:
    return RepairSession(inputs)


def inspect(
    context: RepairInputs,
    published: IntermediateEvidence,
    inventory: Mapping[str, object],
    staged: tuple[str, ...] = (),
) -> Inspection:
    """Validate every present artifact, including exactly one unpublished successor."""
    session = begin(context)
    stage, count, total = _inventory_prefix(published, inventory)
    if session.blocked_reason is not None:
        if stage != "not_started" or total or staged:
            raise ValueError("Blocked preparation has incompatible evidence")
        return Inspection(stage, "not_started", "incomplete", None)
    if stage == "not_started":
        if total or staged:
            raise ValueError("Unstarted preparation has retained evidence")
        return Inspection(stage, stage, "incomplete", None)
    if total < count or total > count + 1:
        raise ValueError("Inventory differs from published prefix by more than one artifact")
    initial = session.pending
    assert initial is not None
    session.confirm_checkpoint(
        CheckpointReceipt(initial.session_id, initial.generation, initial.sha256)
    )
    for kind, reference, _ in ARTIFACTS[:total]:
        payload = inventory[reference]
        pending = session.record(
            kind, payload, ArtifactReceipt(reference, artifact_digest(payload))
        )
        session.confirm_checkpoint(
            CheckpointReceipt(pending.session_id, pending.generation, pending.sha256)
        )
    _validate_staging(staged, total, count)
    return _inspection_result(session, published, stage, total, count)


def _inspection_result(
    session: RepairSession,
    published: IntermediateEvidence,
    stage: str,
    total: int,
    count: int,
) -> Inspection:
    reason = session.checkpoint["reason"] if total == count else None
    if published["reason"] != reason:
        raise ValueError("Checkpoint diagnostic contradicts retained facts")
    action = session.next_action()
    ready = action if isinstance(action, Ready) and total == count else None
    diagnostic: Literal["passed", "failed", "incomplete"] = "incomplete"
    if ready is not None:
        diagnostic = "passed"
    elif isinstance(action, Stop) and total == count:
        diagnostic = action.diagnostic
    return Inspection(stage, STAGES[total + 1], diagnostic, ready)


def _inventory_prefix(
    published: IntermediateEvidence,
    inventory: Mapping[str, object],
) -> tuple[str, int, int]:
    if set(inventory) - {reference for _, reference, _ in ARTIFACTS}:
        raise ValueError("Unknown preparation evidence")
    if set(published) != {"stage", "generation", "reason"}:
        raise ValueError("Malformed preparation checkpoint")
    if type(published["generation"]) is not int or (
        published["reason"] is not None and type(published["reason"]) is not str
    ):
        raise ValueError("Malformed preparation checkpoint values")
    stage = published["stage"]
    if stage not in STAGES:
        raise ValueError("Unknown preparation checkpoint stage")
    count = STAGES.index(stage) - 1
    expected_generation = STAGES.index(stage)
    if published["generation"] != expected_generation:
        raise ValueError("Checkpoint generation contradicts its stage")
    present = [reference in inventory for _, reference, _ in ARTIFACTS]
    if present != sorted(present, reverse=True):
        raise ValueError("Preparation artifacts do not form an ordered prefix")
    return stage, count, sum(present)


def _validate_staging(staged: tuple[str, ...], total: int, count: int) -> None:
    if staged:
        if total != count or total >= len(ARTIFACTS):
            raise ValueError("Snapshot staging requires its immediately preceding checkpoint")
        next_kind, next_reference, _ = ARTIFACTS[total]
        target = PurePosixPath(next_reference)
        for path in staged:
            candidate = PurePosixPath(path)
            temporary = (
                candidate.parent == target.parent
                and re.fullmatch(
                    re.escape("." + target.name + ".") + r"[A-Za-z0-9_-]+\.tmp", candidate.name
                )
                is not None
            )
            snapshot_blob = next_kind in {"before", "after"} and path.startswith(
                f"intermediate/{next_kind}/"
            )
            empty_parent = path.endswith("/") and candidate == target.parent
            if not temporary and not snapshot_blob and not empty_parent:
                raise ValueError("Future or unrelated evidence staging")


def _validate_snapshot(snapshot: FilesystemSnapshot) -> None:
    entries = {(item["root"], item["path"]): item for item in snapshot.entries}
    if len(entries) != len(snapshot.entries):
        raise ValueError("Observation has duplicate entries")
    _validate_obstacles(snapshot)
    for key, entry in entries.items():
        operation = None
        if entry["kind"] == "file" and key not in snapshot.contents:
            operation = "read_file"
        elif entry["kind"] == "directory" and not entry.get("listing_complete"):
            operation = "list_directory"
        elif entry["kind"] == "unknown":
            operation = "stat"
        if operation is not None and not any(
            (item["root"], item["path"], item["operation"]) == (*key, operation)
            for item in snapshot.obstacles
        ):
            raise ValueError("Unavailable observation requires an explicit matching obstacle")
    if any(key not in entries or entries[key]["kind"] != "file" for key in snapshot.contents):
        raise ValueError("Observation bytes require a regular file entry")


def _validate_obstacles(snapshot: FilesystemSnapshot) -> None:
    for obstacle in snapshot.obstacles:
        key = obstacle["root"], obstacle["path"]
        entry = snapshot.entry(*key)
        if entry is None:
            raise ValueError("Observation obstacle requires a matching entry")
        match obstacle["operation"]:
            case "read_file":
                valid = entry["kind"] == "file" and key not in snapshot.contents
            case "list_directory":
                valid = entry["kind"] == "directory" and entry.get("listing_complete") is False
            case "stat":
                valid = entry["kind"] == "unknown"
            case _:
                valid = False
        if not valid:
            raise ValueError("Observation obstacle contradicts retained facts")
