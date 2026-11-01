"""Protected requests, pure preparation, and independently replayed evidence prefixes."""

import copy
import hashlib
from typing import cast

import pytest

from tests.install_sandbox.component.container.test_repair_scenario import KEY, inputs
from tools.install_sandbox.contracts.evidence_layout import StagedEvidence
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    IntermediateEvidence,
    VerificationResult,
)
from tools.install_sandbox.rules import step_lifecycle as lifecycle
from tools.install_sandbox.rules.repair_actions import (
    ARTIFACTS,
    ApplyMarkdownMutation,
    Completion,
    JsonArtifact,
    ObserveSnapshot,
    RetainEvidence,
    SnapshotArtifact,
    artifact_digest,
)
from tools.install_sandbox.rules.repair_protocol import (
    Ready,
    RepairInputs,
    RepairSession,
    Stop,
    begin,
    inspect,
)


def context() -> RepairInputs:
    case, sources, installed, first, verdict = inputs()
    step = lifecycle.start("install")
    for event in (
        lifecycle.PreparationObserved("steps/0/before.json"),
        lifecycle.Prepared(),
        lifecycle.ExpectationsRetained("expectations/install.json"),
        lifecycle.CommandReturned(
            {
                "args": ["install"],
                "cwd": "/sandbox/project",
                "state": "completed",
                "exit_code": 0,
                "reason": None,
                "stdout_file": None,
                "stderr_file": None,
            }
        ),
        lifecycle.CommandRetained("steps/0/stdout.txt", "steps/0/stderr.txt"),
        lifecycle.ObservationRetained("steps/0/after.json"),
        lifecycle.VerificationComputed(verdict),
        lifecycle.VerificationRetained("steps/0/verification.json"),
        lifecycle.Terminate(),
    ):
        step = lifecycle.advance(step, event)
    return RepairInputs(case.to_json().encode(), sources, installed, first, step)


def confirm(session: RepairSession) -> CheckpointReceipt:
    pending = session.pending
    assert pending is not None
    receipt = CheckpointReceipt(pending.session_id, pending.generation, pending.sha256)
    session.confirm_checkpoint(receipt)
    return receipt


# Deliberately independent of the production catalogue.
REFERENCES = (
    "intermediate/operation.json",
    "expectations/intermediate.json",
    "intermediate/repair-plan.json",
    "intermediate/before.json",
    "intermediate/performed.json",
    "intermediate/after.json",
    "intermediate/verification.json",
    "expectations/reinstall.json",
)


def retained(session: RepairSession) -> RetainEvidence:
    request = session.next_action()
    assert isinstance(request, RetainEvidence)
    return request


def observed(session: RepairSession) -> ObserveSnapshot:
    request = session.next_action()
    assert isinstance(request, ObserveSnapshot)
    return request


def applied(session: RepairSession) -> ApplyMarkdownMutation:
    request = session.next_action()
    assert isinstance(request, ApplyMarkdownMutation)
    return request


def completion_for(
    request: RetainEvidence | ObserveSnapshot | ApplyMarkdownMutation | Ready | Stop,
    ctx: RepairInputs,
    *,
    corrupt: bool = False,
    unavailable: bool = False,
) -> Completion:
    if isinstance(request, RetainEvidence):
        return request.completion
    if isinstance(request, ObserveSnapshot) and request.phase == "before":
        return request.complete(ctx.first_after)
    if isinstance(request, ApplyMarkdownMutation):
        operation = request.operation
    else:
        assert isinstance(request, ObserveSnapshot)
        prior = begin(ctx)
        confirm(prior)
        first = prior.next_action()
        assert isinstance(first, RetainEvidence)
        operation = first.completion.value
    assert isinstance(operation, BoundMarkdownMutation)
    after = copy.deepcopy(ctx.first_after)
    document = after.contents[KEY]
    after.contents[KEY] = (
        document[: operation.start] + operation.replacement + document[operation.end :]
    )
    if corrupt:
        after.contents[KEY] += b"personal edit"
    if isinstance(request, ApplyMarkdownMutation):
        return request.complete(
            PerformedMutation(operation, hashlib.sha256(after.contents[KEY]).hexdigest())
        )
    if unavailable:
        after.contents.pop(KEY)
        after.obstacles.append(
            {"operation": "read_file", "root": KEY[0], "path": KEY[1], "reason": "Denied"}
        )
    return request.complete(after)


def accept(session: RepairSession, completion: Completion) -> JsonArtifact | SnapshotArtifact:
    artifact = session.prepare(completion)
    session.record(completion, ArtifactReceipt(artifact.reference, artifact_digest(artifact)))
    return artifact


def advance(
    session: RepairSession,
    ctx: RepairInputs,
    count: int,
    *,
    corrupt: bool = False,
    unavailable: bool = False,
) -> dict[str, object]:
    inventory: dict[str, object] = {}
    confirm(session)
    for reference in REFERENCES[:count]:
        completion = completion_for(
            session.next_action(), ctx, corrupt=corrupt, unavailable=unavailable
        )
        artifact = accept(session, completion)
        assert artifact.reference == reference
        inventory[reference] = completion.value
        confirm(session)
    return inventory


def test_pending_checkpoint_and_consumed_or_foreign_receipts():
    session = begin(context())
    pending = session.pending
    assert pending is not None
    with pytest.raises(ValueError, match="Pending"):
        session.next_action()
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(CheckpointReceipt("foreign", pending.generation, pending.sha256))
    receipt = confirm(session)
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(receipt)
    completion = retained(session).completion
    artifact = session.prepare(completion)
    for receipt in (
        ArtifactReceipt("wrong", artifact_digest(artifact)),
        ArtifactReceipt(artifact.reference, "wrong"),
    ):
        with pytest.raises(ValueError, match="acknowledgement"):
            session.record(completion, receipt)
    accept(session, completion)
    with pytest.raises(ValueError, match="Pending"):
        session.prepare(completion)
    confirm(session)
    with pytest.raises(ValueError, match="active request"):
        session.record(completion, ArtifactReceipt(artifact.reference, artifact_digest(artifact)))


def test_foreign_completion_and_independently_constructed_completion_rejected():
    left, right = begin(context()), begin(context())
    confirm(left)
    confirm(right)
    own, foreign = retained(left), retained(right)
    assert own != foreign
    assert own.completion != foreign.completion
    with pytest.raises(ValueError, match="active request"):
        left.prepare(foreign.completion)
    with pytest.raises(TypeError, match="constructed by their request"):
        Completion(object(), object())


def test_inputs_completion_artifacts_and_pending_are_detached():
    ctx = context()
    session = begin(ctx)
    ctx.first_after.contents.clear()
    ctx.sources.contents.clear()
    pending = session.pending
    assert pending is not None
    pending.checkpoint["stage"] = "ready"
    assert session.pending is not None
    assert session.pending.checkpoint["stage"] == "started"
    confirm(session)
    accept(session, retained(session).completion)
    confirm(session)
    completion = retained(session).completion
    value = completion.value
    assert isinstance(value, ExpectationSet) and value.roots is not None
    value.roots["home"] = "/wrong"
    artifact = session.prepare(completion)
    assert isinstance(artifact, JsonArtifact)
    document = artifact.document
    assert isinstance(document, dict)
    document.clear()
    assert artifact.document and value.roots["home"] == "/wrong"
    saved = completion.value
    assert isinstance(saved, ExpectationSet) and saved.roots is not None
    assert saved.roots["home"] == "/sandbox/home"


def test_prepare_changed_before_is_pure_and_abort_is_idempotent():
    ctx = context()
    session = begin(ctx)
    advance(session, ctx, 3)
    request = observed(session)
    changed = copy.deepcopy(ctx.first_after)
    changed.contents[KEY] += b"external edit"
    completion = request.complete(changed)
    before = session.checkpoint
    artifact = session.prepare(completion)
    assert isinstance(artifact, SnapshotArtifact)
    artifact.snapshot.contents.clear()
    changed.contents.clear()
    saved_value = completion.value
    assert isinstance(saved_value, FilesystemSnapshot)
    assert artifact.snapshot.contents and saved_value.contents
    assert session.checkpoint == before and session.pending is None
    assert session.next_action() is request
    accept(session, completion)
    assert session.pending is not None
    assert session.pending.checkpoint["reason"]
    saved = session.pending
    assert saved is not None
    session.abort()
    session.abort()
    for operation in (
        session.next_action,
        lambda: session.prepare(completion),
        lambda: session.record(
            completion, ArtifactReceipt(artifact.reference, artifact_digest(artifact))
        ),
        lambda: session.confirm_checkpoint(
            CheckpointReceipt(saved.session_id, saved.generation, saved.sha256)
        ),
    ):
        with pytest.raises(ValueError, match="aborted"):
            operation()
    assert session.pending == saved and session.checkpoint == before


@pytest.mark.parametrize("successor", range(8))
def test_one_unpublished_successor_is_valid_without_authorizing_dependents(successor: int) -> None:
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, successor)
    published = session.checkpoint
    completion = completion_for(session.next_action(), ctx)
    accept(session, completion)
    inventory[REFERENCES[successor]] = completion.value
    result = inspect(ctx, published, inventory)
    assert result.diagnostic == "incomplete" and result.ready is None


@pytest.mark.parametrize(
    "corrupt,unavailable,diagnostic",
    [(False, False, "passed"), (True, False, "failed"), (False, True, "incomplete")],
)
def test_ready_or_terminal_verification_replays_at_atomic_publication(
    corrupt: bool, unavailable: bool, diagnostic: str
) -> None:
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, 6, corrupt=corrupt, unavailable=unavailable)
    published = session.checkpoint
    request = retained(session)
    completion = request.completion
    exposed = completion.value
    assert isinstance(exposed, VerificationResult)
    exposed.mismatches.clear()
    artifact = accept(session, completion)
    inventory[artifact.reference] = completion.value
    assert inspect(ctx, published, inventory).diagnostic == "incomplete"
    # Publication is authoritative even before the live session confirms it.
    pending = session.pending
    assert pending is not None
    assert inspect(ctx, pending.checkpoint, inventory).diagnostic == (
        diagnostic if diagnostic != "passed" else "incomplete"
    )
    confirm(session)
    if diagnostic == "passed":
        completion = retained(session).completion
        artifact = accept(session, completion)
        inventory[artifact.reference] = completion.value
        confirm(session)
        assert isinstance(session.next_action(), Ready)
    else:
        assert isinstance(session.next_action(), Stop)
    assert inspect(ctx, session.checkpoint, inventory).diagnostic == diagnostic
    terminal_staging = StagedEvidence(
        "literal-terminal-staging", "json_temporary", frozenset({"expectations/reinstall.json"})
    )
    with pytest.raises(ValueError, match="staging"):
        inspect(ctx, session.checkpoint, inventory, (terminal_staging,))


def test_wrong_result_types_and_contradictory_observations_rejected_without_changes():
    ctx = context()
    session = begin(ctx)
    advance(session, ctx, 3)
    request = observed(session)
    with pytest.raises(ValueError, match="observation"):
        request.complete(cast(FilesystemSnapshot, object()))
    broken = copy.deepcopy(ctx.first_after)
    broken.contents.pop(KEY)
    checkpoint = session.checkpoint
    with pytest.raises(ValueError, match="explicit matching obstacle"):
        session.prepare(request.complete(broken))
    assert session.checkpoint == checkpoint and session.pending is None
    accept(session, request.complete(ctx.first_after))
    confirm(session)
    mutation = applied(session)
    with pytest.raises(ValueError, match="performed mutation"):
        mutation.complete(cast(PerformedMutation, ctx.first_after))
    accept(session, mutation.complete(PerformedMutation(mutation.operation, "0" * 64)))
    confirm(session)
    with pytest.raises(ValueError, match="contradicts"):
        session.prepare(observed(session).complete(ctx.first_after))


def test_changed_before_stops_effects_and_rejects_later_evidence():
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, 3)
    changed = copy.deepcopy(ctx.first_after)
    changed.contents[KEY] += b"external edit"
    completion = observed(session).complete(changed)
    artifact = accept(session, completion)
    inventory[artifact.reference] = completion.value
    confirm(session)
    assert isinstance(session.next_action(), Stop)
    assert inspect(ctx, session.checkpoint, inventory).diagnostic == "incomplete"
    with pytest.raises(ValueError, match="staging"):
        inspect(
            ctx,
            session.checkpoint,
            inventory,
            (
                StagedEvidence(
                    "literal-staging", "json_temporary", frozenset({"intermediate/performed.json"})
                ),
            ),
        )
    inventory["intermediate/performed.json"] = object()
    with pytest.raises(ValueError, match="published prefix"):
        inspect(ctx, session.checkpoint, inventory)


def test_replay_rejects_tampered_retention_and_future_or_missing_evidence():
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, 2)
    expectations = inventory["expectations/intermediate.json"]
    assert isinstance(expectations, ExpectationSet) and expectations.roots is not None
    expectations.roots["home"] = "/wrong"
    with pytest.raises(ValueError, match="contradicts"):
        inspect(ctx, session.checkpoint, inventory)
    fresh = begin(ctx)
    confirm(fresh)
    with pytest.raises(ValueError, match="staging"):
        inspect(
            ctx,
            fresh.checkpoint,
            {},
            (StagedEvidence("arbitrary", "snapshot_blob", frozenset({"intermediate/after.json"})),),
        )
    with pytest.raises(ValueError, match="ordered prefix"):
        inspect(ctx, fresh.checkpoint, {"intermediate/performed.json": object()})
    assert (
        inspect(
            ctx,
            fresh.checkpoint,
            {},
            (
                StagedEvidence(
                    "arbitrary", "json_temporary", frozenset({"intermediate/operation.json"})
                ),
            ),
        ).diagnostic
        == "incomplete"
    )


def test_catalogue_codecs_roundtrip_logical_facts():
    ctx = context()
    session = begin(ctx)
    confirm(session)
    for descriptor in ARTIFACTS:
        completion = completion_for(session.next_action(), ctx)
        artifact = session.prepare(completion)
        raw = artifact.document if isinstance(artifact, JsonArtifact) else artifact.snapshot
        decoded = descriptor.decode(raw)
        assert artifact_digest(decoded) == artifact_digest(completion.value)
        accept(session, completion)
        confirm(session)


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"stage": "unknown", "generation": 0, "reason": None},
        {"stage": "started", "generation": True, "reason": None},
        {"stage": "started", "generation": 2, "reason": None},
        {"stage": "started", "generation": 1, "reason": 3},
    ],
)
def test_malformed_checkpoint_is_invalid(checkpoint: object) -> None:
    with pytest.raises(ValueError):
        inspect(context(), cast(IntermediateEvidence, checkpoint), {})


def test_foreign_performed_operation_cannot_be_retained() -> None:
    from dataclasses import replace

    ctx = context()
    session = begin(ctx)
    advance(session, ctx, 4)
    request = applied(session)
    other = replace(request.operation, replacement=b"different mutation")
    completion = request.complete(PerformedMutation(other, "0" * 64))
    checkpoint = session.checkpoint
    with pytest.raises(ValueError, match="contradicts"):
        session.prepare(completion)
    assert session.checkpoint == checkpoint and session.pending is None
    assert session.next_action() is request


def test_unavailable_before_is_retainable_but_cannot_authorize_mutation() -> None:
    ctx = context()
    session = begin(ctx)
    advance(session, ctx, 3)
    observation = copy.deepcopy(ctx.first_after)
    observation.contents.pop(KEY)
    observation.obstacles.append(
        {"operation": "read_file", "root": KEY[0], "path": KEY[1], "reason": "Denied"}
    )
    accept(session, observed(session).complete(observation))
    confirm(session)
    assert isinstance(session.next_action(), Stop)


def test_same_digest_wrong_logical_type_is_rejected_during_replay() -> None:
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, 1)
    operation = inventory[REFERENCES[0]]
    assert isinstance(operation, BoundMarkdownMutation)
    # A decoded dictionary could hash identically but is not a decoded operation.
    inventory[REFERENCES[0]] = operation.to_data()
    with pytest.raises(ValueError, match="Wrong result type"):
        inspect(ctx, session.checkpoint, inventory)


@pytest.mark.parametrize("successor", range(8))
def test_staging_rejected_after_complete_unpublished_successor(successor: int) -> None:
    ctx = context()
    session = begin(ctx)
    inventory = advance(session, ctx, successor)
    published = session.checkpoint
    completion = completion_for(session.next_action(), ctx)
    accept(session, completion)
    inventory[REFERENCES[successor]] = completion.value
    with pytest.raises(ValueError, match="staging"):
        inspect(
            ctx,
            published,
            inventory,
            (StagedEvidence("literal", "json_temporary", frozenset({REFERENCES[successor]})),),
        )


def test_json_action_rejects_snapshot_staging_even_with_matching_owner() -> None:
    ctx = context()
    session = begin(ctx)
    confirm(session)
    with pytest.raises(ValueError, match="staging"):
        inspect(
            ctx,
            session.checkpoint,
            {},
            (StagedEvidence("literal", "snapshot_blob", frozenset({REFERENCES[0]})),),
        )
