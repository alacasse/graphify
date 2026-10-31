"""Publication gates, detached baselines, and replayed prefixes."""

import copy
import hashlib
from pathlib import Path
from typing import cast

import pytest

from tests.install_sandbox.component.container.test_repair_scenario import KEY, inputs
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    StepEvidence,
    VerificationResult,
)
from tools.install_sandbox.rules.repair_protocol import (
    ARTIFACTS,
    Action,
    Ready,
    RepairInputs,
    RepairSession,
    Stop,
    artifact_digest,
    begin,
    inspect,
)


def context() -> RepairInputs:
    case, sources, installed, first, verdict = inputs()
    step = cast(
        StepEvidence,
        {
            "progress": "finished",
            "operation": "install",
            "skip_reason": None,
            "command": {
                "args": ["install"],
                "cwd": "/sandbox/project",
                "state": "completed",
                "exit_code": 0,
                "reason": None,
                "stdout_file": None,
                "stderr_file": None,
            },
            "verification": verdict,
            "observations": {"before": "steps/0/before.json", "after": "steps/0/after.json"},
        },
    )
    return RepairInputs(case.to_json().encode(), sources, installed, first, step)


def confirm(session: RepairSession) -> CheckpointReceipt:
    pending = session.pending
    assert pending is not None
    receipt = CheckpointReceipt(pending.session_id, pending.generation, pending.sha256)
    session.confirm_checkpoint(receipt)
    return receipt


def record(session: RepairSession, payload: object) -> None:
    action = session.next_action()
    assert isinstance(action, Action)
    session.record(
        action.kind, payload, ArtifactReceipt(action.reference, artifact_digest(payload))
    )


def through(session: RepairSession, kind: str) -> dict[str, object]:
    inventory: dict[str, object] = {}
    confirm(session)
    while True:
        action = session.next_action()
        assert isinstance(action, Action)
        if action.kind == kind:
            return inventory
        record(session, action.payload)
        inventory[action.reference] = action.payload
        confirm(session)


def test_pending_checkpoint_blocks_actions_and_rejects_foreign_consumed_receipts() -> None:
    session = begin(context())
    pending = session.pending
    assert pending is not None
    with pytest.raises(ValueError, match="Pending"):
        session.next_action()
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(CheckpointReceipt("foreign", pending.generation, pending.sha256))
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(
            CheckpointReceipt(pending.session_id, pending.generation, "wrong")
        )
    receipt = confirm(session)
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(receipt)
    action = session.next_action()
    assert isinstance(action, Action)
    with pytest.raises(ValueError, match="acknowledgement"):
        session.record(action.kind, action.payload, ArtifactReceipt(action.reference, "wrong"))
    record(session, action.payload)
    with pytest.raises(ValueError, match="Pending"):
        session.next_action()


def test_inputs_actions_and_pending_are_detached_from_mutable_callers() -> None:
    original = context()
    session = begin(original)
    pending = session.pending
    assert pending is not None
    pending.checkpoint["stage"] = "ready"
    original.first_after.contents.clear()
    original.first_after.entries.clear()
    original.sources.contents.clear()
    assert original.installed.roots is not None
    original.installed.roots["home"] = "/wrong"
    assert session.pending is not None and session.pending.checkpoint["stage"] == "started"
    confirm(session)
    operation = session.next_action()
    assert isinstance(operation, Action)
    record(session, operation.payload)
    confirm(session)
    expectations = session.next_action()
    assert isinstance(expectations, Action)
    assert isinstance(expectations.payload, ExpectationSet)
    assert expectations.payload.roots is not None
    assert expectations.payload.roots["home"] == "/sandbox/home"


@pytest.mark.parametrize("successor", range(len(ARTIFACTS)))
def test_honest_artifact_one_ahead_is_valid_but_cannot_authorize_dependents(successor: int) -> None:
    ctx = context()
    session = begin(ctx)
    inventory = through(session, "before")
    before = copy.deepcopy(ctx.first_after)
    operation = inventory["intermediate/operation.json"]
    assert isinstance(operation, BoundMarkdownMutation)
    after = copy.deepcopy(before)
    document = before.contents[KEY]
    after.contents[KEY] = (
        document[: operation.start] + operation.replacement + document[operation.end :]
    )
    performed = PerformedMutation(operation, hashlib.sha256(after.contents[KEY]).hexdigest())
    # Rebuild every prefix from independently selected physical observations.
    session = begin(ctx)
    confirm(session)
    inventory: dict[str, object] = {}
    for index in range(successor + 1):
        action = session.next_action()
        assert isinstance(action, Action)
        payload = {"before": before, "after": after, "performed": performed}.get(
            action.kind, action.payload
        )
        checkpoint = session.checkpoint
        record(session, payload)
        inventory[action.reference] = payload
        if index == successor:
            result = inspect(ctx, checkpoint, inventory)
            assert result.diagnostic == "incomplete" and result.ready is None
            break
        confirm(session)


def test_ready_uses_prepared_baseline_and_failed_mutation_cannot_launder_changes() -> None:
    for corrupt in (False, True):
        ctx = context()
        session = begin(ctx)
        inventory = through(session, "before")
        record(session, ctx.first_after)
        confirm(session)
        operation = inventory["intermediate/operation.json"]
        assert isinstance(operation, BoundMarkdownMutation)
        after = copy.deepcopy(ctx.first_after)
        document = after.contents[KEY]
        after.contents[KEY] = document[: operation.start] + document[operation.end :]
        if corrupt:
            after.contents[KEY] += b"unexpected personal edit"
        record(
            session, PerformedMutation(operation, hashlib.sha256(after.contents[KEY]).hexdigest())
        )
        confirm(session)
        record(session, after)
        after.contents.clear()
        confirm(session)
        action = session.next_action()
        assert isinstance(action, Action) and action.kind == "verification"
        record(session, action.payload)
        confirm(session)
        next_action = session.next_action()
        if corrupt:
            assert isinstance(next_action, Stop) and next_action.diagnostic == "failed"
        else:
            assert isinstance(next_action, Action) and next_action.kind == "effective_expectations"
            assert next_action.payload != inventory["intermediate/repair-plan.json"]
            record(session, next_action.payload)
            confirm(session)
            assert isinstance(session.next_action(), Ready)


def test_blocked_and_unstarted_inventory_is_always_checked() -> None:
    ctx = context()
    ctx.first_step["progress"] = "incomplete"
    with pytest.raises(ValueError):
        inspect(
            ctx,
            {"stage": "not_started", "generation": 0, "reason": None},
            {"expectations/reinstall.json": object()},
        )


def test_future_staging_and_missing_predecessors_are_invalid() -> None:
    ctx = context()
    session = begin(ctx)
    confirm(session)
    with pytest.raises(ValueError, match="staging"):
        inspect(ctx, session.checkpoint, {}, ("intermediate/after/0.bin",))
    with pytest.raises(ValueError, match="ordered prefix"):
        inspect(ctx, session.checkpoint, {"intermediate/performed.json": object()})


def test_external_verdict_mutation_cannot_authorize_preparation() -> None:
    ctx = context()
    verdict = ctx.first_step["verification"]
    assert verdict is not None
    from tools.install_sandbox.contracts.results import VerificationMismatch

    verdict.mismatches.append(VerificationMismatch("content", *KEY, "good", "bad"))
    session = begin(ctx)
    verdict.mismatches.clear()
    assert isinstance(session.next_action(), Stop)


def test_returned_verdict_mutation_cannot_authorize_effective_expectations() -> None:
    ctx = context()
    session = begin(ctx)
    inventory = through(session, "before")
    record(session, ctx.first_after)
    confirm(session)
    operation = inventory["intermediate/operation.json"]
    assert isinstance(operation, BoundMarkdownMutation)
    after = copy.deepcopy(ctx.first_after)
    record(session, PerformedMutation(operation, hashlib.sha256(after.contents[KEY]).hexdigest()))
    confirm(session)
    record(session, after)
    confirm(session)
    action = session.next_action()
    assert isinstance(action, Action)
    record(session, action.payload)
    assert isinstance(action.payload, VerificationResult)
    action.payload.mismatches.clear()
    confirm(session)
    assert isinstance(session.next_action(), Stop)


def test_changed_before_observation_stops_mutation_and_rejects_later_evidence() -> None:
    ctx = context()
    session = begin(ctx)
    inventory = through(session, "before")
    changed = copy.deepcopy(ctx.first_after)
    changed.contents[KEY] += b"external edit"
    action = session.next_action()
    assert isinstance(action, Action)
    record(session, changed)
    inventory[action.reference] = changed
    confirm(session)
    assert isinstance(session.next_action(), Stop)
    assert inspect(ctx, session.checkpoint, inventory).diagnostic == "incomplete"
    operation = inventory["intermediate/operation.json"]
    assert isinstance(operation, BoundMarkdownMutation)
    inventory["intermediate/performed.json"] = PerformedMutation(operation, "0" * 64)
    with pytest.raises(ValueError, match="published prefix"):
        inspect(ctx, session.checkpoint, inventory)


def test_performed_digest_contradiction_is_invalid_even_before_verdict() -> None:
    ctx = context()
    session = begin(ctx)
    inventory = through(session, "before")
    record(session, ctx.first_after)
    confirm(session)
    operation = inventory["intermediate/operation.json"]
    assert isinstance(operation, BoundMarkdownMutation)
    record(session, PerformedMutation(operation, "0" * 64))
    confirm(session)
    with pytest.raises(ValueError, match="contradicts"):
        record(session, ctx.first_after)


def test_atomic_temporary_files_are_allowed_only_for_next_unpublished_artifact() -> None:
    ctx = context()
    session = begin(ctx)
    confirm(session)
    assert (
        inspect(ctx, session.checkpoint, {}, ("intermediate/.operation.json.token.tmp",)).diagnostic
        == "incomplete"
    )
    with pytest.raises(ValueError, match="staging"):
        inspect(ctx, session.checkpoint, {}, ("intermediate/.performed.json.token.tmp",))
    action = session.next_action()
    assert isinstance(action, Action)
    with pytest.raises(ValueError, match="preceding checkpoint"):
        inspect(
            ctx,
            session.checkpoint,
            {action.reference: action.payload},
            ("expectations/.intermediate.json.token.tmp",),
        )


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
    from tools.install_sandbox.contracts.results import IntermediateEvidence

    with pytest.raises(ValueError):
        inspect(context(), cast(IntermediateEvidence, checkpoint), {})


def test_missing_snapshot_bytes_without_read_obstacle_are_invalid() -> None:
    ctx = context()
    session = begin(ctx)
    through(session, "before")
    broken = copy.deepcopy(ctx.first_after)
    broken.contents.pop(KEY)
    with pytest.raises(ValueError, match="explicit matching obstacle"):
        record(session, broken)


def test_snapshot_read_obstacle_stops_preparation_honestly() -> None:
    ctx = context()
    session = begin(ctx)
    through(session, "before")
    blocked = copy.deepcopy(ctx.first_after)
    blocked.contents.pop(KEY)
    blocked.obstacles.append(
        {"operation": "read_file", "root": KEY[0], "path": KEY[1], "reason": "Denied"}
    )
    record(session, blocked)
    confirm(session)
    result = session.next_action()
    assert isinstance(result, Stop) and result.diagnostic == "incomplete"


@pytest.mark.parametrize("field,value", [("stage", "ready"), ("reason", "altered")])
def test_writer_checkpoint_receipt_binds_actual_published_checkpoint(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter
    from tools.install_sandbox.contracts.results import InstallTestResult

    session = begin(context())
    pending = session.pending
    assert pending is not None
    if field == "stage":
        pending.checkpoint["stage"] = value
    else:
        pending.checkpoint["reason"] = value
    result = InstallTestResult(
        {"name": "test", "target": "controlled", "scope": "project"},
        {
            "source": "campaign",
            "ready": True,
            "reason": None,
            "log": "preparation.log",
            "stage": "initial_verified",
        },
        [],
        "incomplete",
        {},
    )
    receipt = TestResultWriter(tmp_path).write_checkpoint(result, pending)
    with pytest.raises(ValueError, match="acknowledgement"):
        session.confirm_checkpoint(receipt)
    with pytest.raises(ValueError, match="Pending"):
        session.next_action()
