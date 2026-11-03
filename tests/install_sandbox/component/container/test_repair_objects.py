"""Counterexamples for object invariants and durable publication windows."""

from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, cast

import pytest

from tests.install_sandbox.component.container.repair_support import replay, run_fixture
from tools.install_sandbox.container.case_publication import CasePublisher
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    EvidenceWriteError,
    SnapshotEntry,
)
from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact
from tools.install_sandbox.rules.repair_protocol import (
    RepairInputs,
    RepairSession,
)


@pytest.mark.parametrize("case", ["missing-section", "altered-section"])
@pytest.mark.parametrize("phase", ["before", "after"])
def test_failure_after_snapshot_blobs_before_publication_is_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, case: str
):
    original = Writer.retain

    def interrupt(self: Writer, artifact: JsonArtifact | SnapshotArtifact) -> ArtifactReceipt:
        receipt = original(self, artifact)
        if artifact.reference == f"intermediate/{phase}.json":
            raise OSError("Interrupted after durable snapshot before acknowledgement")
        return receipt

    monkeypatch.setattr(Writer, "retain", interrupt)
    outcome = run_fixture(tmp_path, {"case": case})
    assert outcome["run_status"] == outcome["replay_status"] == "incomplete"
    assert outcome["calls"] == 1
    assert (Path(outcome["proof"]) / "intermediate" / f"{phase}.json").exists()
    assert replay(Path(outcome["proof"])) == "incomplete"


def test_writer_rejects_corrupted_retained_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.contracts.results import EvidenceWriteError

    writer = Writer(tmp_path)

    def corrupt(relative: str, document: object) -> None:
        (tmp_path / relative).write_text('{"different": true}')

    monkeypatch.setattr(writer, "_write_json", corrupt)
    with pytest.raises(EvidenceWriteError, match="differs"):
        writer.retain(JsonArtifact("artifact.json", {"expected": True}))


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
    from collections.abc import Callable
    from typing import cast

    from tools.install_sandbox.container.environment import ObservedEnvironment
    from tools.install_sandbox.contracts.results import SnapshotEntry

    original = cast(
        Callable[[ObservedEnvironment, FilesystemSnapshot, SnapshotEntry, Path], None],
        vars(ObservedEnvironment)["_file"],
    )
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
    snapshot = FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry,
                {
                    "root": "project",
                    "path": "GUIDE.md",
                    "kind": "file",
                    "content_file": None,
                    "sha256": None,
                },
            )
        ]
    )
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


class ProcessDisappeared(BaseException):
    pass


class CapturedExecution(TypedDict, total=False):
    session: RepairSession
    writer: Writer
    mutations: int
    retry: Callable[[], object]


def capture_execution(monkeypatch: pytest.MonkeyPatch, captured: CapturedExecution) -> None:
    from tools.install_sandbox.container import intermediate_execution

    begin = intermediate_execution.begin
    apply = intermediate_execution.apply_mutation
    advance = cast(
        Callable[
            [RepairSession, RepairInputs, EffectEnvironment, Writer, CasePublisher], object
        ],
        vars(intermediate_execution)["_advance"],
    )

    def capture_advance(
        session: RepairSession,
        inputs: RepairInputs,
        environment: EffectEnvironment,
        writer: Writer,
        publisher: CasePublisher,
    ) -> object:
        captured["retry"] = lambda: advance(session, inputs, environment, writer, publisher)
        return advance(session, inputs, environment, writer, publisher)

    def begin_session(inputs: RepairInputs) -> RepairSession:
        session = begin(inputs)
        captured["session"] = session
        return session

    def mutate(
        operation: BoundMarkdownMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        apply(operation, environment, case_bytes, first_after, sources)
        captured["mutations"] = captured.get("mutations", 0) + 1

    monkeypatch.setattr(intermediate_execution, "_advance", capture_advance)
    monkeypatch.setattr(intermediate_execution, "begin", begin_session)
    monkeypatch.setattr(
        "tests.install_sandbox.component.container.repair_support.apply_mutation", mutate
    )


def interrupt_execution(
    monkeypatch: pytest.MonkeyPatch, window: str, failure: type[BaseException]
) -> CapturedExecution:
    captured: CapturedExecution = {"mutations": 0}
    original_retain = Writer.retain
    original_publication = CasePublisher.publish_repair
    original_confirm = RepairSession.confirm_checkpoint
    capture_execution(monkeypatch, captured)

    def retain(writer: Writer, artifact: JsonArtifact | SnapshotArtifact) -> ArtifactReceipt:
        captured["writer"] = writer
        if window == "mutation-retention" and artifact.reference == "intermediate/performed.json":
            assert captured.get("mutations") == 1
            raise failure("Controlled retention interruption")
        return original_retain(writer, artifact)

    def publication(publisher: CasePublisher, session: RepairSession) -> None:
        captured["writer"] = publisher.writer
        if window == "initial" and not publisher.writer.halted:
            raise failure("Controlled initial publication interruption")
        return original_publication(publisher, session)

    def confirm(session: RepairSession, receipt: CheckpointReceipt) -> None:
        if window == "confirmation" and session is captured.get("session"):
            raise failure("Controlled confirmation interruption")
        return original_confirm(session, receipt)

    monkeypatch.setattr(Writer, "retain", retain)
    monkeypatch.setattr(CasePublisher, "publish_repair", publication)
    monkeypatch.setattr(RepairSession, "confirm_checkpoint", confirm)
    return captured


@pytest.mark.parametrize("case", ["missing-section", "altered-section"])
@pytest.mark.parametrize("window", ["initial", "mutation-retention", "confirmation"])
@pytest.mark.parametrize("disappearance", [False, True])
def test_escaping_failure_aborts_session_and_halts_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: str, disappearance: bool, case: str
) -> None:
    failure = ProcessDisappeared if disappearance else OSError
    captured = interrupt_execution(monkeypatch, window, failure)
    if disappearance:
        with pytest.raises(ProcessDisappeared):
            run_fixture(tmp_path, {"case": case})
    else:
        outcome = run_fixture(tmp_path, {"case": case})
        assert outcome["run_status"] == outcome["replay_status"] == "incomplete"
        assert outcome["calls"] == 1
    assert "writer" in captured and "session" in captured and "retry" in captured
    assert captured["writer"].halted
    session = captured["session"]
    with pytest.raises(ValueError):
        session.next_action()
    session.abort()  # Idempotent after a physical failure.
    if window == "mutation-retention":
        assert captured.get("mutations") == 1
    published = tmp_path / "proof/result.json"
    before_retry = published.read_bytes()
    mutations = captured.get("mutations")
    with pytest.raises((ValueError, EvidenceWriteError)):
        captured["retry"]()
    assert published.read_bytes() == before_retry
    assert captured.get("mutations") == mutations
    assert replay(tmp_path / "proof") == "incomplete"


def test_writer_verifies_retained_snapshot_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.contracts.results import EvidenceWriteError

    writer = Writer(tmp_path)
    snapshot = FilesystemSnapshot(
        entries=[cast(SnapshotEntry, {"root": "project", "path": "target", "kind": "file"})],
        contents={("project", "target"): b"Observed bytes"},
    )
    from collections.abc import Callable

    write = cast(Callable[..., None], vars(Writer)["_write_bytes"])

    def corrupt(relative: str, content: bytes, *, append: bool = False) -> None:
        write(writer, relative, b"Corrupted bytes", append=append)

    monkeypatch.setattr(writer, "_write_bytes", corrupt)
    with pytest.raises(EvidenceWriteError, match="snapshot differs"):
        writer.retain(SnapshotArtifact("intermediate/before.json", snapshot))
