"""Retained hook evidence and dependent-step protection through the local runner."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.host.hook_evidence_support import JSON, run
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize(
    "name,phase",
    [
        ("first-install", "steps/0/before"),
        ("first-install", "steps/0/after"),
        ("reinstall", "steps/0/after"),
        ("reinstall", "steps/1/before"),
        ("reinstall", "steps/1/after"),
    ],
)
@pytest.mark.parametrize(
    "corruption", ["missing_content", "missing_entry", "digest_only", "wrong_binding"]
)
def test_hook_proof_cannot_be_omitted_or_rebound(
    tmp_path: Path, name: str, phase: str, corruption: str
) -> None:
    case, output = run(tmp_path, name)
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case).status == "passed"
    path = output / f"{phase}.json"
    snapshot = json.loads(path.read_bytes())
    entry = next(e for e in snapshot["entries"] if e["root"] == "project" and e["path"] == JSON)
    if corruption == "missing_content":
        (output / entry["content_file"]).unlink()
    elif corruption == "missing_entry":
        snapshot["entries"].remove(entry)
    elif corruption == "digest_only":
        entry.pop("content_file")
        entry["sha256"] = "a" * 64
    else:
        entry["content_file"] = f"steps/9/after/project/{JSON}"
    path.write_text(json.dumps(snapshot))
    with pytest.raises((ValueError, FileNotFoundError)):
        read_result(output, case)


@pytest.mark.parametrize(
    "damage",
    [
        "data['hooks']['PreToolUse'][0]['hooks'].pop()",
        "data['hooks']['PreToolUse'][0]['hooks'].pop(0)",
    ],
)
def test_first_hook_failure_blocks_reinstall_and_keeps_diagnostics(
    tmp_path: Path, damage: str
) -> None:
    script = (
        f"p = Path({JSON!r}); data = json.loads(p.read_text())\n"
        + damage
        + "\np.write_text(json.dumps(data))\n"
    )
    case, output = run(tmp_path, "reinstall", damage=script)
    shutil.rmtree(tmp_path / "work")
    result = read_result(output, case)
    assert result.steps[1]["command"] is None
    assert result.steps[1]["skip_reason"]
    verification = result.steps[0]["verification"]
    assert verification is not None and verification.mismatches
    assert not (output / "steps/1/after.json").exists()
    saved: dict[str, Any] = json.loads((output / "steps/0/verification.json").read_bytes())
    assert json.loads(saved["mismatches"][0]["observed"])["count"] == 0
    saved["mismatches"][0]["observed"] = "Changed diagnostic"
    (output / "steps/0/verification.json").write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="differs"):
        read_result(output, case)
