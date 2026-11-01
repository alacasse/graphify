"""Replay independently retained bytes; these fixtures never execute the runner."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    payload = json.loads(
        (Path(__file__).parents[2] / "fixtures/retained-markdown-proof.json").read_text()
    )
    for reference, content in payload.items():
        destination = tmp_path / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    return tmp_path


def declaration(phase: str = "preparation") -> dict[str, Any]:
    return {
        "operation": "install",
        "phase": phase,
        "facts": {"prepared": False, "command": None, "verification": None},
        "retained": {
            "before": None,
            "before_usable": True,
            "expectations": None,
            "command": False,
            "after": None,
            "verification": None,
        },
        "stop": None,
    }


def retain_begin(archive: Path, index: int = 0) -> dict[str, Any]:
    result = json.loads((archive / "result.json").read_text())
    result["status"] = "incomplete"
    result["steps"][index] = declaration()
    if index == 0:
        result["steps"][1] = declaration("idle")
        shutil.rmtree(archive / "steps/1")
        (archive / "expectations/reinstall.json").unlink()
    for name in ("after.json", "verification.json", "environment.json", "stdout.txt", "stderr.txt"):
        (archive / f"steps/{index}/{name}").unlink()
    shutil.rmtree(archive / f"steps/{index}/after")
    (archive / "result.json").write_text(json.dumps(result))
    return result


def test_begin_accepts_environment_stdout_prefix_without_promotion(archive: Path) -> None:
    environment = (archive / "steps/0/environment.json").read_bytes()
    retain_begin(archive)
    (archive / "steps/0/environment.json").write_bytes(environment)
    (archive / "steps/0/stdout.txt").write_bytes(b"partial output")
    assert read_evidence(archive).status == "incomplete"


@pytest.mark.parametrize("extra", ["unknown.json", "stderr.txt", "after.json", "verification.json"])
def test_begin_rejects_unknown_future_or_nonprefix_artifacts(archive: Path, extra: str) -> None:
    original = (archive / f"steps/0/{extra}").read_bytes() if extra != "unknown.json" else b"{}"
    retain_begin(archive)
    (archive / f"steps/0/{extra}").write_bytes(original)
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


def test_command_publication_with_complete_extra_observation_remains_incomplete(
    archive: Path,
) -> None:
    result = json.loads((archive / "result.json").read_text())
    result["status"] = "incomplete"
    step = result["steps"][0]
    step["phase"] = "observation"
    step["facts"]["verification"] = None
    step["retained"].update(after=None, verification=None)
    result["steps"][1] = declaration("idle")
    shutil.rmtree(archive / "steps/1")
    (archive / "expectations/reinstall.json").unlink()
    (archive / "result.json").write_text(json.dumps(result))
    assert read_evidence(archive).status == "incomplete"


@pytest.mark.parametrize(
    "extra", [".after.json.spare.tmp", "after/project/unreferenced.txt", "unknown.txt"]
)
def test_terminal_rejects_unreferenced_staging_and_unknown_paths(archive: Path, extra: str) -> None:
    (archive / f"steps/0/{extra}").write_bytes(b"unreferenced")
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


@pytest.mark.parametrize("published_failure", [False, True])
@pytest.mark.parametrize("obstacle", [False, True])
def test_divergent_before1_is_readable_but_cannot_authorize_command(
    archive: Path, published_failure: bool, obstacle: bool
) -> None:
    result = retain_begin(archive, 1)
    (archive / "expectations/reinstall.json").unlink()
    path = archive / "steps/1/before.json"
    before = json.loads(path.read_text())
    if obstacle:
        before["obstacles"] = [
            {"operation": "read", "root": "project", "path": "GUIDE.md", "reason": "unreadable"}
        ]
    else:
        content = b"Divergent baseline.\n"
        (archive / "steps/1/before/project/GUIDE.md").write_bytes(content)
        for entry in before["entries"]:
            if entry["root"] == "project" and entry["path"] == "GUIDE.md":
                entry["sha256"] = hashlib.sha256(content).hexdigest()
    path.write_text(json.dumps(before))
    if published_failure:
        stopped = declaration("stopped")
        stopped["retained"].update(before="steps/1/before.json", before_usable=False)
        stopped["stop"] = {"phase": "preparation", "reason": "Prior observation changed"}
        (archive / "steps/1/failure.json").write_text(json.dumps(stopped))
        result["steps"][1] = stopped
        (archive / "result.json").write_text(json.dumps(result))
    assert read_evidence(archive).status == "incomplete"
    (archive / "steps/1/stdout.txt").write_bytes(b"forbidden command")
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


@pytest.mark.parametrize("future_phase", ["observation", "verification_evidence"])
def test_failure_ahead_requires_coherent_acquired_facts(archive: Path, future_phase: str) -> None:
    retain_begin(archive)
    stopped = declaration("stopped")
    stopped["stop"] = {"phase": future_phase, "reason": "forged progress"}
    (archive / "steps/0/failure.json").write_text(json.dumps(stopped))
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


def test_error_diagnostic_ahead_of_begin_is_readable(archive: Path) -> None:
    retain_begin(archive)
    (archive / "expectations/install.json").unlink()
    stopped = declaration("stopped")
    stopped["retained"]["before"] = "steps/0/before.json"
    stopped["stop"] = {"phase": "preparation", "reason": "controlled failure"}
    (archive / "steps/0/failure.json").write_text(json.dumps(stopped))
    assert read_evidence(archive).status == "incomplete"


def test_begin_reinstall_accepts_partial_before_snapshot_without_manifest(archive: Path) -> None:
    retain_begin(archive, 1)
    (archive / "expectations/reinstall.json").unlink()
    (archive / "steps/1/before.json").unlink()
    assert (archive / "steps/1/before/project/GUIDE.md").exists()
    assert read_evidence(archive).status == "incomplete"


@pytest.mark.parametrize(
    "extra",
    [
        "expectations/.reinstall.json.spare.tmp",
        "steps/2/unexpected.txt",
        "expectations/unexpected.json",
    ],
)
def test_terminal_rejects_extra_expectations_and_unknown_steps(archive: Path, extra: str) -> None:
    path = archive / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}")
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)


def test_unavailable_preparation_cannot_hide_forged_idle_command_facts(archive: Path) -> None:
    result = json.loads((archive / "result.json").read_text())
    command = result["steps"][0]["facts"]["command"]
    result["status"] = "not_run"
    result["preparation"].update(ready=False, reason="unavailable")
    result["steps"] = [declaration("idle"), declaration("idle")]
    result["steps"][0]["facts"]["command"] = command
    (archive / "result.json").write_text(json.dumps(result))
    with pytest.raises(MalformedEvidence, match="Command facts contradict phase"):
        read_evidence(archive)


@pytest.mark.parametrize("state", [[], {}, True, 1])
def test_malformed_command_state_is_rejected_as_evidence(archive: Path, state: object) -> None:
    result = json.loads((archive / "result.json").read_text())
    result["steps"][0]["facts"]["command"]["state"] = state
    (archive / "result.json").write_text(json.dumps(result))
    with pytest.raises(MalformedEvidence):
        read_evidence(archive)
