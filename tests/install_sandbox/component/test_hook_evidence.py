"""Retained hook evidence and dependent-step protection through the local runner."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.test_local_runner import LocalCase, controlled_script
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import InstallTestCoordinator
from tools.install_sandbox.result_reader import read_result
from tools.install_sandbox.runner import InstallTestRunner

_SPECS = Path(__file__).resolve().parents[3] / "tools/install_sandbox/specs/reference"
_JSON = ".sandbox-reference/settings.json"


def _run(tmp_path: Path, name: str, *, damage: str = "") -> tuple[InstallTestCase, Path]:
    local = LocalCase(tmp_path)
    case = InstallTestCoordinator().write_case(
        _SPECS, "sandbox-reference", tmp_path / "case.json", case_name=name
    )
    executable = local.prepare_executable()
    executable.write_text(controlled_script("passed") + damage)
    result = InstallTestRunner().run_case(
        reference_sources=tmp_path / "subject",
        prepared_executable=executable,
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "results",
    )
    assert result.status == ("failed" if damage else "passed"), result
    return case, tmp_path / "results"


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
    case, output = _run(tmp_path, name)
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case).status == "passed"
    path = output / f"{phase}.json"
    snapshot = json.loads(path.read_bytes())
    entry = next(e for e in snapshot["entries"] if e["root"] == "project" and e["path"] == _JSON)
    if corruption == "missing_content":
        (output / entry["content_file"]).unlink()
    elif corruption == "missing_entry":
        snapshot["entries"].remove(entry)
    elif corruption == "digest_only":
        entry.pop("content_file")
        entry["sha256"] = "a" * 64
    else:
        entry["content_file"] = f"steps/9/after/project/{_JSON}"
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
        f"p = Path({_JSON!r}); data = json.loads(p.read_text())\n"
        + damage
        + "\np.write_text(json.dumps(data))\n"
    )
    case, output = _run(tmp_path, "reinstall", damage=script)
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
