"""Closed, effect-free protocol for retained Markdown preparation evidence."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileRemoval,
    BoundMarkdownMutation,
    PerformedMutation,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.evidence_layout import StagedEvidence
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot, same_observation
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    RepairCheckpoint,
    RepairProgress,
    StepState,
    VerificationResult,
)
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import preservation_baseline
from tools.install_sandbox.rules.repair_actions import (
    ARTIFACTS,
    ApplyMutation,
    ArtifactDescriptor,
    Completion,
    JsonArtifact,
    ObserveSnapshot,
    Request,
    RetainEvidence,
    SnapshotArtifact,
    artifact_digest,
)
from tools.install_sandbox.rules.repair_scenario import MarkdownRepairScenario, PreparationBlocked
from tools.install_sandbox.rules.step_lifecycle import status

STAGES = ("not_started", "started", *(item.checkpoint for item in ARTIFACTS))


def checkpoint_digest(checkpoint: RepairCheckpoint) -> str:
    """Bind acknowledgement to immutable local checkpoint content."""
    return artifact_digest(checkpoint.to_data())


def _conforming(verdict: VerificationResult) -> bool:
    return verdict.complete and not verdict.mismatches and not verdict.obstacles


@dataclass(frozen=True)
class RepairInputs:
    case_bytes: bytes
    sources: FilesystemSnapshot
    installed: ExpectationSet
    first_after: FilesystemSnapshot
    first_step: StepState


@dataclass(frozen=True)
class PendingCheckpoint:
    progress: RepairProgress
    session_id: str
    generation: int
    sha256: str


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
    progress: RepairProgress
    ready: Ready | None


class RepairSession:
    """Detached facts are private; every returned value is a detached copy."""

    def __init__(self, inputs: RepairInputs) -> None:
        self._inputs = copy.deepcopy(inputs)
        self.session_id = uuid.uuid4().hex
        self._index = -1
        self._active: Request | None = None
        self._aborted = False
        self._payloads: dict[str, object] = {}
        self._reason: str | None = None
        self._pending: PendingCheckpoint | None = None
        self._progress = RepairProgress(RepairCheckpoint("not_started", 0), "incomplete")
        first = self._inputs.first_step
        verdict = first.verification
        self._blocked: str | None = None
        if status(first) != "passed" or verdict is None:
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
    def progress(self) -> RepairProgress:
        return self._progress

    def _make_pending(self, stage: str, generation: int) -> PendingCheckpoint:
        checkpoint = RepairCheckpoint(stage, generation, self._reason)
        stop = self._stop()
        outcome = (
            stop.diagnostic
            if stop is not None
            else ("ready" if self._index == len(ARTIFACTS) - 1 else "incomplete")
        )
        progress = RepairProgress(checkpoint, outcome)
        self._pending = PendingCheckpoint(
            progress, self.session_id, generation, checkpoint_digest(checkpoint)
        )
        return self._pending

    def abort(self) -> None:
        """Permanently halt physical execution without changing recorded facts."""
        self._aborted = True

    def _require_live(self) -> None:
        if self._aborted:
            raise ValueError("Repair session aborted")

    def confirm_checkpoint(self, receipt: CheckpointReceipt) -> None:
        self._require_live()
        pending = self._pending
        if pending is None or (
            receipt.session_id != pending.session_id
            or receipt.generation != pending.generation
            or receipt.sha256 != pending.sha256
        ):
            raise ValueError("Checkpoint acknowledgement does not match pending publication")
        self._progress = pending.progress
        self._pending = None

    def next_action(self) -> Request | Ready | Stop:
        self._require_live()
        if self._pending is not None:
            raise ValueError("Pending checkpoint publication blocks dependent actions")
        outcome = self._stop()
        if outcome is not None:
            return outcome
        assert self._plan is not None
        if self._index == len(ARTIFACTS) - 1:
            return Ready(copy.deepcopy(self._effective()), copy.deepcopy(self._after()))
        if self._active is None:
            kind = ARTIFACTS[self._index + 1].kind
            if kind == "before" or kind == "after":
                self._active = ObserveSnapshot(kind)
            elif kind == "performed":
                operation = self._payloads["operation"]
                assert isinstance(operation, (BoundMarkdownMutation, BoundFileRemoval))
                self._active = ApplyMutation(operation)
            else:
                self._active = RetainEvidence(self._retained_value(kind))
        return self._active

    def _stop(self) -> Stop | None:
        """One terminal decision for pending publication, execution and replay."""
        reason = self._blocked or self._reason
        if reason is None:
            return None
        verdict = self._payloads.get("verification")
        failed = (
            isinstance(verdict, VerificationResult)
            and verdict.complete
            and bool(verdict.mismatches)
        )
        return Stop(reason, "failed" if failed else "incomplete")

    def _retained_value(self, kind: str) -> object:
        assert self._plan is not None
        match kind:
            case "operation":
                return self._plan.operation
            case "preparation_expectations":
                return self._plan.after_preparation_expectations
            case "repair_plan":
                return self._plan.second_install_expectations
            case "verification":
                return EffectVerifier().verify(
                    self._plan.after_preparation_expectations, self._after()
                )
            case "effective_expectations":
                return self._effective()
            case _:
                raise ValueError("No retained value for physical request")

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

    def _prepared(self, completion: object) -> tuple[JsonArtifact | SnapshotArtifact, str | None]:
        request = self.next_action()
        if (
            not isinstance(request, (RetainEvidence, ObserveSnapshot, ApplyMutation))
            or not isinstance(completion, Completion)
            or not completion.belongs_to(request)
        ):
            raise ValueError("Completion does not follow the published prefix or active request")
        descriptor = ARTIFACTS[self._index + 1]
        payload = completion.value
        artifact = descriptor.encode(payload)
        expected = request.completion.value if isinstance(request, RetainEvidence) else None
        reason = self._validate(descriptor.kind, payload, expected)
        return artifact, reason

    def prepare(self, completion: Completion) -> JsonArtifact | SnapshotArtifact:
        """Validate and encode a detached artifact without accepting facts or diagnostics."""
        artifact, _ = self._prepared(completion)
        return artifact

    def record(
        self, completion: Completion, artifact_receipt: ArtifactReceipt
    ) -> PendingCheckpoint:
        artifact, reason = self._prepared(completion)
        if (
            artifact_receipt.reference != artifact.reference
            or artifact_receipt.sha256 != artifact_digest(artifact)
        ):
            raise ValueError("Artifact acknowledgement differs from retained content")
        descriptor = ARTIFACTS[self._index + 1]
        self._payloads[descriptor.kind] = completion.value
        self._reason = reason or self._reason
        self._index += 1
        self._active = None
        return self._make_pending(descriptor.checkpoint, self._progress.checkpoint.generation + 1)

    def _validate(self, kind: str, payload: object, expected: object) -> str | None:
        reason = None
        if kind in {"operation", "performed"}:
            self._validate_mutation(kind, payload)
        elif kind in {"before", "after"}:
            reason = self._validate_observation(kind, payload)
        elif artifact_digest(payload) != artifact_digest(expected):
            raise ValueError("Evidence contradicts independently reconstructed expectations")
        if kind == "verification":
            if not isinstance(payload, VerificationResult):
                raise ValueError("Expected preparation verdict")
            if not _conforming(payload):
                reason = "Preparation verification failed or incomplete"
        return reason

    def _validate_mutation(self, kind: str, payload: object) -> None:
        assert self._plan is not None
        if kind == "operation":
            if not isinstance(payload, (BoundMarkdownMutation, BoundFileRemoval)):
                raise ValueError("Expected bound mutation")
            if payload != self._plan.operation:
                raise ValueError("Operation destination differs from case")
            payload.verify_binding(self._inputs.case_bytes, self._inputs.first_after)
        elif (
            not isinstance(payload, PerformedMutation)
            or payload.operation != self._payloads["operation"]
        ):
            raise ValueError("Performed mutation contradicts retained operation")

    def _validate_observation(self, kind: str, payload: object) -> str | None:
        if not isinstance(payload, FilesystemSnapshot):
            raise ValueError("Expected preparation observation")
        _validate_snapshot(payload)
        if kind == "before":
            if not same_observation(self._inputs.first_after, payload):
                return "Environment changed before mutation or observation obstructed"
            return None
        performed = self._payloads["performed"]
        operation = self._payloads["operation"]
        assert isinstance(performed, PerformedMutation)
        assert isinstance(operation, (BoundMarkdownMutation, BoundFileRemoval))
        performed.verify(operation, payload)
        return None


def begin(inputs: RepairInputs) -> RepairSession:
    return RepairSession(inputs)


def inspect(
    context: RepairInputs,
    published: RepairCheckpoint,
    inventory: Mapping[str, object],
    staged: tuple[StagedEvidence, ...] = (),
) -> Inspection:
    """Replay the published prefix, then validate one successor without promoting it."""
    session = begin(context)
    stage, count, total = _inventory_prefix(published, inventory)
    if session.blocked_reason is not None and stage != "not_started":
        raise ValueError("Blocked preparation has incompatible evidence")
    if stage == "not_started":
        if total or staged:
            raise ValueError("Unstarted preparation has retained evidence")
        if published != session.progress.checkpoint:
            raise ValueError("Checkpoint diagnostic contradicts retained facts")
        return Inspection(session.progress, None)
    if total < count or total > count + 1:
        raise ValueError("Inventory differs from published prefix by more than one artifact")
    _replay_published_prefix(session, inventory, count)
    progress = session.progress
    if published != progress.checkpoint:
        raise ValueError("Checkpoint diagnostic contradicts retained facts")
    action = session.next_action()
    ready = action if isinstance(action, Ready) else None
    _validate_staging(staged, total, count, action)
    if total > count:
        descriptor = ARTIFACTS[count]
        completion = _replay_completion(action, descriptor, inventory[descriptor.reference])
        session.prepare(completion)
    return Inspection(progress, ready)


def _replay_published_prefix(
    session: RepairSession, inventory: Mapping[str, object], count: int
) -> None:
    """Acknowledge only the artifacts covered by the published checkpoint."""
    initial = session.pending
    assert initial is not None
    session.confirm_checkpoint(
        CheckpointReceipt(initial.session_id, initial.generation, initial.sha256)
    )
    for descriptor in ARTIFACTS[:count]:
        payload = inventory[descriptor.reference]
        completion = _replay_completion(session.next_action(), descriptor, payload)
        pending = session.record(
            completion, ArtifactReceipt(descriptor.reference, artifact_digest(payload))
        )
        session.confirm_checkpoint(
            CheckpointReceipt(pending.session_id, pending.generation, pending.sha256)
        )


def _replay_completion(
    request: Request | Ready | Stop, descriptor: ArtifactDescriptor, payload: object
) -> Completion:
    """Reconstruct a request-bound completion from independently decoded facts."""
    if isinstance(request, RetainEvidence):
        descriptor.encode(payload)
        completion = request.completion
        if artifact_digest(payload) != artifact_digest(completion.value):
            raise ValueError("Evidence contradicts independently reconstructed expectations")
        return completion
    if isinstance(request, ObserveSnapshot):
        if not isinstance(payload, FilesystemSnapshot):
            raise ValueError("Expected preparation observation")
        return request.complete(payload)
    if isinstance(request, ApplyMutation):
        if not isinstance(payload, PerformedMutation):
            raise ValueError("Expected performed mutation")
        return request.complete(payload)
    raise ValueError("Artifact does not follow the published prefix")


def _inventory_prefix(
    published: RepairCheckpoint,
    inventory: Mapping[str, object],
) -> tuple[str, int, int]:
    if set(inventory) - {item.reference for item in ARTIFACTS}:
        raise ValueError("Unknown preparation evidence")
    # Decode again to reject invalid directly constructed values.
    RepairCheckpoint.from_data(published.to_data())
    stage = published.stage
    if stage not in STAGES:
        raise ValueError("Unknown preparation checkpoint stage")
    count = STAGES.index(stage) - 1
    expected_generation = STAGES.index(stage)
    if published.generation != expected_generation:
        raise ValueError("Checkpoint generation contradicts its stage")
    present = [item.reference in inventory for item in ARTIFACTS]
    if present != sorted(present, reverse=True):
        raise ValueError("Preparation artifacts do not form an ordered prefix")
    return stage, count, sum(present)


def _validate_staging(
    staged: tuple[StagedEvidence, ...], total: int, count: int, action: Request | Ready | Stop
) -> None:
    if not staged:
        return
    if total != count or total >= len(ARTIFACTS) or isinstance(action, (Stop, Ready)):
        raise ValueError("Evidence staging requires an authorized next action")
    descriptor = ARTIFACTS[total]
    forms = {"json_temporary", "directory"}
    if descriptor.transport == "snapshot":
        forms.add("snapshot_blob")
    if any(descriptor.reference not in item.owners or item.form not in forms for item in staged):
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
