"""Counterexamples for object invariants and durable publication windows."""

from pathlib import Path
import pytest
from tools.install_sandbox.container.environment import FilesystemSnapshot
from experiment_adapter import run_fixture, replay
from tools.install_sandbox.contracts.repair_progress import RepairProgress, DurableArtifact
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer


def test_progress_is_immutable_and_rejects_skipped_transitions() -> None:
    initial = RepairProgress()
    running = initial.begin()
    assert initial.progress == "not_started"
    with pytest.raises(ValueError):
        running.retained_after(DurableArtifact("intermediate/after.json"))
    with pytest.raises(ValueError):
        running.retained_operation(DurableArtifact("steps/0/after.json"))
    with pytest.raises(ValueError):
        RepairProgress(progress="finished")
    with pytest.raises(ValueError):
        RepairProgress.from_data({**running.to_data(), "foreign": True})
    op = running.retained_operation(DurableArtifact("intermediate/operation.json"))
    with pytest.raises(ValueError):
        op.retained_operation(DurableArtifact("intermediate/operation.json"))


@pytest.mark.parametrize("phase", ["before", "after"])
def test_failure_after_snapshot_blobs_before_publication_is_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
):
    original = Writer.write_intermediate_snapshot

    def interrupt(self: Writer, snapshot: FilesystemSnapshot, name: str) -> None:
        original(self, snapshot, name)
        if name == phase:
            raise OSError("Interrupted after durable snapshot before acknowledgement")

    monkeypatch.setattr(Writer, "write_intermediate_snapshot", interrupt)
    outcome = run_fixture(tmp_path, {"case": "missing-section"})
    assert outcome["run_status"] == outcome["replay_status"] == "incomplete"
    assert outcome["calls"] == 1
    assert (Path(outcome["proof"]) / "intermediate" / f"{phase}.json").exists()
    assert replay(Path(outcome["proof"])) == "incomplete"


def test_writer_does_not_acknowledge_missing_artifact(tmp_path: Path) -> None:
    writer = Writer(tmp_path)
    with pytest.raises(Exception, match="not been retained"):
        writer.acknowledge("intermediate/after.json")


def test_nonconformant_progress_cannot_be_changed_through_verdict_alias() -> None:
    from tools.install_sandbox.contracts.results import VerificationMismatch, VerificationResult

    progress = RepairProgress().begin()
    progress = progress.retained_operation(DurableArtifact("intermediate/operation.json"))
    progress = progress.retained_expectations(DurableArtifact("expectations/intermediate.json"))
    progress = progress.retained_before(DurableArtifact("intermediate/before.json"))
    progress = progress.retained_after(DurableArtifact("intermediate/after.json"))
    supplied = VerificationResult(
        mismatches=[VerificationMismatch("bad", "project", "GUIDE.md", "good", "bad")]
    )
    verified = progress.verified(DurableArtifact("intermediate/verification.json"), supplied)
    supplied.mismatches.clear()
    assert not verified.permits_repair()
    serialized = verified.to_data()
    assert serialized["verification"] is not None
    serialized["verification"].mismatches.clear()
    assert not verified.permits_repair()


def test_later_metadata_is_forbidden_without_durable_operation(tmp_path: Path) -> None:
    result = run_fixture(tmp_path, {"case": "missing-section", "fault": "persist-before-mutation"})
    assert result["replay_status"] == "incomplete"
    proof = Path(result["proof"])
    (proof / "intermediate").mkdir(exist_ok=True)
    (proof / "intermediate/after.json").write_text("{}")
    assert replay(proof) == "invalid"


def test_bad_mutation_operation_tamper_is_invalid(tmp_path: Path) -> None:
    import json

    result = run_fixture(tmp_path, {"case": "missing-section", "fault": "wrong-mutation"})
    assert result["run_status"] == result["replay_status"] == "failed"
    proof = Path(result["proof"])
    path = proof / "intermediate/operation.json"
    data = json.loads(path.read_text())
    data.update(start=0, end=1)
    path.write_text(json.dumps(data))
    assert replay(proof) == "invalid"


@pytest.mark.parametrize("case", ["missing-section", "altered-section"])
def test_target_read_obstacle_after_mutation_replays_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from tools.install_sandbox.container.environment import ObservedEnvironment
    from tools.install_sandbox.contracts.results import SnapshotEntry

    from collections.abc import Callable
    from typing import cast

    original = cast(Callable[[ObservedEnvironment, FilesystemSnapshot, SnapshotEntry, Path], None],
                    getattr(ObservedEnvironment, "_file"))
    captures = 0

    def capture(
        self: ObservedEnvironment, snapshot: FilesystemSnapshot, entry: SnapshotEntry, path: Path
    ) -> None:
        nonlocal captures
        if entry["root"] == "project" and entry["path"] == "GUIDE.md":
            captures += 1
            if captures == 4:
                entry["content_file"] = None
                snapshot.obstacles.append(
                    {
                        "operation": "read_file",
                        "root": "project",
                        "path": "GUIDE.md",
                        "reason": "Unavailable target bytes",
                    }
                )
                return
        original(self, snapshot, entry, path)

    monkeypatch.setattr(ObservedEnvironment, "_file", capture)
    outcome = run_fixture(tmp_path, {"case": case})
    assert outcome["run_status"] == outcome["replay_status"] == "incomplete"
    assert outcome["calls"] == 1
    assert not (tmp_path / "subject").exists() and not (tmp_path / "work").exists()
    assert replay(Path(outcome["proof"])) == "incomplete"


def test_performed_receipt_does_not_mask_missing_or_conflicting_bytes(tmp_path: Path) -> None:
    import json
    from tools.install_sandbox.contracts.bound_mutation import PerformedMutation

    outcome = run_fixture(tmp_path, {"case": "missing-section", "fault": "wrong-mutation"})
    assert outcome["run_status"] == outcome["replay_status"] == "failed"
    performed = PerformedMutation.from_data(
        json.loads((Path(outcome["proof"]) / "intermediate/performed.json").read_text())
    )
    snapshot = FilesystemSnapshot(entries=[{"root": "project", "path": "GUIDE.md", "kind": "file"}])
    with pytest.raises(ValueError, match="bytes or explicit read obstacle"):
        performed.verify(performed.operation, snapshot)
    snapshot.obstacles.append(
        {
            "operation": "read_file",
            "root": "project",
            "path": "GUIDE.md",
            "reason": "Unavailable target bytes",
        }
    )
    performed.verify(performed.operation, snapshot)
    snapshot.contents[("project", "GUIDE.md")] = b"Present but different bytes."
    with pytest.raises(ValueError, match="contradicts"):
        performed.verify(performed.operation, snapshot)
