"""Replay case dependencies from independent literal archives without a runner."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.contracts.results import StepState
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


@pytest.fixture(params=["markdown", "altered"])
def archive(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    fixture = Path(__file__).parents[2] / f"fixtures/retained-{request.param}-proof.json"
    for reference, content in json.loads(fixture.read_text()).items():
        path = tmp_path / "archive" / reference
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path / "archive"


def load(output: Path) -> dict[str, Any]:
    return json.loads((output / "result.json").read_text())


def publish(output: Path, result: dict[str, Any]) -> None:
    (output / "result.json").write_text(json.dumps(result))


@pytest.mark.parametrize("status", ["failed", "not_run", "incomplete"])
def test_forged_aggregate_status_rejected(archive: Path, status: str) -> None:
    result = load(archive)
    result["status"] = status
    publish(archive, result)
    with pytest.raises(MalformedEvidence, match="status"):
        read_evidence(archive)


def test_archive_replays_without_source_or_work_directories(archive: Path) -> None:
    assert not (archive.parent / "work").exists()
    assert not (archive.parent / "subject").exists()
    assert read_evidence(archive).status == "passed"


def test_unpublished_first_verification_cannot_authorize_second_step(archive: Path) -> None:
    result = load(archive)
    first = result["steps"][0]
    first["phase"] = "observation"
    first["facts"]["verification"] = None
    first["retained"].update(after=None, verification=None)
    result["status"] = "incomplete"
    publish(archive, result)
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


def test_advanced_first_proof_does_not_promote_published_progress(archive: Path) -> None:
    result = load(archive)
    if result["intermediate_preparation"] is not None:
        pytest.skip("Repair needs its own publication prefix")
    result["steps"][1] = StepState.idle("install").to_data()
    shutil.rmtree(archive / "steps/1")
    (archive / "expectations/reinstall.json").unlink()
    first = result["steps"][0]
    first["phase"] = "observation"
    first["facts"]["verification"] = None
    first["retained"].update(after=None, verification=None)
    result["status"] = "incomplete"
    publish(archive, result)
    replayed = read_evidence(archive)
    assert replayed.status == "incomplete"
    assert replayed.steps[0].verification is None
    result["status"] = "passed"
    publish(archive, result)
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


@pytest.mark.parametrize("second_started", [False, True])
def test_retained_repair_success_cannot_promote_checkpoint(
    archive: Path, second_started: bool
) -> None:
    result = load(archive)
    repair = result["intermediate_preparation"]
    if repair is None:
        pytest.skip("Ordinary case has no repair")
    repair.update(stage="verification_retained", generation=8)
    result["status"] = "incomplete"
    if not second_started:
        result["steps"][1] = StepState.idle("install").to_data()
        shutil.rmtree(archive / "steps/1")
    publish(archive, result)
    if second_started:
        with pytest.raises(MalformedEvidence):
            read_evidence(archive)
    else:
        replayed = read_evidence(archive)
        assert replayed.status == "incomplete"
        assert replayed.intermediate_preparation == repair
        result["status"] = "passed"
        publish(archive, result)
        with pytest.raises(MalformedEvidence):
            read_evidence(archive)
