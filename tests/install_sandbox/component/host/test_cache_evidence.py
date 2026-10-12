"""The host requires retained independent lock expectations and observable bytes."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.hook_evidence_support import run
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize("damage", ["missing", "path", "home", "skill"])
def test_rejects_missing_or_inconsistent_lock_expectation(tmp_path: Path, damage: str) -> None:
    case, output = run(tmp_path, "reinstall")
    path = output / "skill-lock.json"
    if damage == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_bytes())
        key = {"path": "path", "home": "home", "skill": "skill_directory"}[damage]
        data[key] += "-wrong"
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        read_result(output, case)


@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
def test_lock_digest_cannot_replace_retained_bytes(tmp_path: Path, phase: str) -> None:
    case, output = run(tmp_path, "reinstall")
    lock = json.loads((output / "skill-lock.json").read_bytes())["path"]
    path = output / (phase + ".json")
    data = json.loads(path.read_bytes())
    entry = next(e for e in data["entries"] if e["root"] == "home" and e["path"] == lock)
    entry.pop("content_file")
    entry["sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="retained bytes"):
        read_result(output, case)


def test_missing_retained_lock_content_is_rejected(tmp_path: Path) -> None:
    case, output = run(tmp_path, "first-install")
    lock = json.loads((output / "skill-lock.json").read_bytes())["path"]
    (output / "steps/0/after/home" / lock).unlink()
    with pytest.raises(OSError):
        read_result(output, case)


@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
def test_missing_whole_lock_observation_cannot_pass(tmp_path: Path, phase: str) -> None:
    case, output = run(tmp_path, "reinstall")
    lock = json.loads((output / "skill-lock.json").read_bytes())["path"]
    path = output / (phase + ".json")
    data = json.loads(path.read_bytes())
    entry = next(e for e in data["entries"] if e["root"] == "home" and e["path"] == lock)
    (output / entry["content_file"]).unlink()
    data["entries"].remove(entry)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="requires observed lock bytes"):
        read_result(output, case)
