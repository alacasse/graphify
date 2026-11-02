"""Case publication verifies the full document before any dependent effect."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.test_step_publication import ControlledRun
from tools.install_sandbox.container.case_publication import CasePublisher
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.container.evidence_writer import result_document
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import (
    CheckpointReceipt,
    EvidenceWriteError,
    InstallTestResult,
)
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence
from tools.install_sandbox.rules.initial_preparation import InitialPreparationLifecycle
from tools.install_sandbox.rules.repair_protocol import RepairSession

JOINTS = [
    (case, boundary)
    for case in ("reinstall", "missing-section", "altered-section")
    for boundary in ("initial", "first", "final")
] + [(case, "repair") for case in ("missing-section", "altered-section")]


def matches(document: dict[str, Any], boundary: str) -> bool:
    initial = document["preparation"]["checkpoint"]
    first, second = (item["phase"] for item in document["steps"])
    repair = document["intermediate_preparation"]
    if boundary == "initial":
        return initial == "ready" and first == "idle"
    if boundary == "first":
        return first == "terminal" and second == "idle" and (
            repair is None or repair["stage"] == "not_started"
        )
    if boundary == "repair":
        return repair is not None and repair["stage"] == "ready" and second == "idle"
    return second == "terminal"


def stopped_run(subject: ControlledRun, boundary: str) -> None:
    if boundary == "repair":
        assert subject.run().status == "incomplete"
    else:
        with pytest.raises(EvidenceWriteError):
            subject.run()
    assert len(subject.calls) == {"initial": 0, "first": 1, "repair": 1, "final": 2}[boundary]
    assert not list(subject.output.glob("steps/*/failure.json"))
    assert not (subject.output / "initial/failure.json").exists()


def remove_external_inputs(subject: ControlledRun) -> None:
    shutil.rmtree(subject.native.root / "subject")
    shutil.rmtree(subject.native.root / "work")
    (subject.native.root / "case.json").unlink()


@pytest.mark.parametrize(("case_name", "boundary"), JOINTS)
def test_document_read_failure_keeps_memory_behind_disk_and_stops_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str, boundary: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original = CasePublisher._verify  # pyright: ignore[reportPrivateUsage]
    attempts: list[CasePublisher] = []
    previous: list[InstallTestResult] = []

    def verify(publisher: CasePublisher, expected: dict[str, object]) -> None:
        if matches(expected, boundary):
            attempts.append(publisher)
            previous.append(publisher.result)
            raise OSError("Controlled result read failure")
        original(publisher, expected)

    monkeypatch.setattr(CasePublisher, "_verify", verify)
    stopped_run(subject, boundary)
    assert len(attempts) == 1 and attempts[0].writer.halted
    assert attempts[0].result is previous[0]
    assert not matches(result_document(previous[0]), boundary)
    remove_external_inputs(subject)
    replayed = read_evidence(subject.output)
    assert replayed.status == ("passed" if boundary == "final" else "incomplete")
    assert matches(subject.saved(), boundary)


@pytest.mark.parametrize(("case_name", "boundary"), JOINTS)
@pytest.mark.parametrize("field", ["status", "case", "evidence"])
def test_altered_full_document_is_rejected_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    boundary: str,
    field: str,
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original = Writer.write_result
    attempts: list[InstallTestResult] = []

    def publish(writer: Writer, result: InstallTestResult) -> None:
        original(writer, result)
        path = writer.output_directory / "result.json"
        document = json.loads(path.read_bytes())
        if matches(document, boundary):
            attempts.append(result)
            if field == "status":
                document[field] = "failed"
            elif field == "case":
                document[field]["name"] = "unrelated"
            else:
                document[field]["journal"] = "unrelated.log"
            path.write_text(json.dumps(document))

    monkeypatch.setattr(Writer, "write_result", publish)
    stopped_run(subject, boundary)
    assert len(attempts) == 1
    if field != "evidence":
        with pytest.raises(MalformedEvidence):
            read_evidence(subject.output)
    assert subject.saved()[field] != (
        attempts[0].status if field == "status" else getattr(attempts[0], field)
    )


@pytest.mark.parametrize("case_name", ["reinstall", "missing-section", "altered-section"])
def test_initial_acknowledgement_failure_keeps_published_ready_without_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original = InitialPreparationLifecycle.acknowledge
    attempts: list[InitialPreparationLifecycle] = []

    def acknowledge(lifecycle: InitialPreparationLifecycle, state: InitialPreparationState) -> None:
        if state.checkpoint == "ready":
            attempts.append(lifecycle)
            raise ValueError("Controlled initial acknowledgement failure")
        original(lifecycle, state)

    monkeypatch.setattr(InitialPreparationLifecycle, "acknowledge", acknowledge)
    stopped_run(subject, "initial")
    assert len(attempts) == 1
    assert attempts[0].published is not None and attempts[0].published.checkpoint == "verified"
    remove_external_inputs(subject)
    assert read_evidence(subject.output).preparation.checkpoint == "ready"


@pytest.mark.parametrize("case_name", ["missing-section", "altered-section"])
def test_repair_acknowledgement_failure_keeps_memory_at_confirmed_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original = RepairSession.confirm_checkpoint
    attempts: list[RepairSession] = []

    def acknowledge(session: RepairSession, receipt: CheckpointReceipt) -> None:
        pending = session.pending
        if pending is not None and pending.progress.outcome == "ready":
            attempts.append(session)
            raise ValueError("Controlled repair acknowledgement failure")
        original(session, receipt)

    monkeypatch.setattr(RepairSession, "confirm_checkpoint", acknowledge)
    stopped_run(subject, "repair")
    assert len(attempts) == 1
    assert attempts[0].progress.checkpoint.stage == "verification_retained"
    monkeypatch.setattr(RepairSession, "confirm_checkpoint", original)
    remove_external_inputs(subject)
    replayed = read_evidence(subject.output)
    assert replayed.intermediate_preparation is not None
    assert replayed.intermediate_preparation["stage"] == "ready"
    assert replayed.status == "incomplete"
