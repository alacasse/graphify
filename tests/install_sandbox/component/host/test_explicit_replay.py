"""Component proof from dedicated retained data, without running upstream layers."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.results import StepState
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


@pytest.fixture
def proof(tmp_path: Path) -> Path:
    payload = json.loads(
        (Path(__file__).parents[2] / "fixtures/retained-markdown-proof.json").read_text()
    )
    for relative, content in payload.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_autonomous_replay_from_dedicated_retained_data(proof: Path) -> None:
    assert read_evidence(proof).status == "passed"


@pytest.mark.parametrize("phase", ["initial", "install", "reinstall"])
def test_missing_phase_expectations_are_rejected(proof: Path, phase: str) -> None:
    (proof / f"expectations/{phase}.json").unlink()
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)


def test_provenance_tampering_is_rejected(proof: Path) -> None:
    path = proof / "expectations/install.json"
    data = json.loads(path.read_text())
    data["expectations"][0]["provenance"] = "unrelated-source"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="expectations contradict"):
        read_evidence(proof)


def test_phase_continuity_tampering_is_rejected(proof: Path) -> None:
    path = proof / "steps/1/before.json"
    data = json.loads(path.read_text())
    data["entries"] = [entry for entry in data["entries"] if entry["path"] != "GUIDE.md"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="observation contradicts"):
        read_evidence(proof)


@pytest.mark.parametrize(
    "version",
    [
        "effects-v1",
        "explicit-expectations-v3",
        "explicit-expectations-v5",
        "explicit-expectations-v6",
    ],
)
def test_historical_transport_is_explicitly_rejected(proof: Path, version: str) -> None:
    path = proof / "evidence-format.json"
    path.write_text(json.dumps({"format": version}))
    with pytest.raises(ValueError, match="historical reader"):
        read_evidence(proof)


@pytest.mark.parametrize("leftover", ["observations", "expectations"])
def test_skipped_phase_rejects_retained_execution_evidence(proof: Path, leftover: str) -> None:
    import shutil

    path = proof / "result.json"
    data = json.loads(path.read_text())
    data["status"] = "failed"
    data["steps"][0]["facts"]["command"]["exit_code"] = 7
    data["steps"][1] = StepState.idle("install").to_data()
    path.write_text(json.dumps(data))
    if leftover == "observations":
        (proof / "expectations/reinstall.json").unlink()
    else:
        shutil.rmtree(proof / "steps/1")
    with pytest.raises(ValueError):
        read_evidence(proof)


def test_ready_result_rejects_retained_initial_failure(proof: Path) -> None:
    (proof / "initial/failure.json").write_text("{}")
    with pytest.raises(ValueError):
        read_evidence(proof)


@pytest.mark.parametrize(
    "retained_artifact",
    [
        None,
        "steps/1/after.json",
        "expectations/install.json",
        "steps/0/after.json",
        "steps/0/stdout.txt",
    ],
)
def test_rejected_initial_verification_forbids_retained_execution(
    proof: Path,
    retained_artifact: str | None,
) -> None:
    import shutil

    (proof / "initial/before/project/GUIDE.md").write_text("Altered initial guide.\n")
    verdict = {
        "complete": True,
        "obstacles": [],
        "mismatches": [
            {
                "type": "content_mismatch",
                "root": "project",
                "path": "GUIDE.md",
                "expected": "bytes identical to retained source",
                "observed": "different bytes",
            }
        ],
    }
    (proof / "initial-verification.json").write_text(json.dumps(verdict))
    result_file = proof / "result.json"
    result = json.loads(result_file.read_text())
    result["status"] = "not_run"
    result["preparation"]["checkpoint"] = "blocked"
    result["preparation"]["facts"]["completed"].pop()
    result["preparation"]["facts"]["verification_passed"] = False
    result["preparation"]["retained"]["install_expectations"] = None
    _retain_changed_guide_digest(proof)
    result["steps"] = [StepState.idle("install").to_data() for _ in range(2)]
    result_file.write_text(json.dumps(result))
    retained = None if retained_artifact is None else (proof / retained_artifact).read_bytes()
    shutil.rmtree(proof / "steps/1")
    for relative in (
        "expectations/install.json",
        "expectations/reinstall.json",
        "steps/0/after.json",
        "steps/0/environment.json",
        "steps/0/stdout.txt",
        "steps/0/stderr.txt",
        "steps/0/verification.json",
    ):
        (proof / relative).unlink()
    shutil.rmtree(proof / "steps/0/after")
    (proof / "steps/0").rmdir()
    if retained_artifact is not None:
        path = proof / retained_artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        assert retained is not None
        path.write_bytes(retained)
        with pytest.raises(ValueError):
            read_evidence(proof)
        return
    assert read_evidence(proof).status == "not_run"


def _retain_changed_guide_digest(proof: Path) -> None:
    # Keep the manifest digest consistent: this is a real nonconforming observation.
    import hashlib

    before_file = proof / "initial/before.json"
    before = json.loads(before_file.read_text())
    for entry in before["entries"]:
        if entry["root"] == "project" and entry["path"] == "GUIDE.md":
            entry["sha256"] = hashlib.sha256(b"Altered initial guide.\n").hexdigest()
    before_file.write_text(json.dumps(before))
