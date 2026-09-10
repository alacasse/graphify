"""Host rejects missing or contradictory repair evidence after controlled execution."""

from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_repair_references import arrange_repair, run_repair


def _corrupt_after_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    program = Path(__file__).with_name("controlled_repair_case.py")
    adapter = tmp_path / "corrupt-evidence.py"
    adapter.write_text(
        "import json, sys, subprocess\nfrom pathlib import Path\n"
        f"subprocess.run([sys.executable, {str(program)!r}, *sys.argv[1:]], check=True)\n"
        "output = Path(sys.argv[3])\n"
        'document = json.loads((output / "result.json").read_bytes())\n'
        '(output / "uncorrupted-result.json").write_text(json.dumps(document))\n' + code + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(adapter))


@pytest.mark.parametrize(
    "relative",
    [
        "journal.log",
        "preparation.log",
        "steps/1/preparation/plan.json",
        "steps/1/preparation/result.json",
        "steps/1/preparation/altered-content.bin",
        "steps/1/before.json",
        "steps/0/after.json",
        "steps/1/after.json",
        "expected.json",
        "steps/1/verification.json",
        "steps/0/stdout.txt",
        "steps/1/before/project/.sandbox-reference/skills/graphify/references/sub/two.md",
        "expected/graphify/skills/claude/references/one.md",
    ],
)
def test_missing_proof_is_reported_by_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    _corrupt_after_run(tmp_path, monkeypatch, f"(output / {relative!r}).unlink()")
    result = run_repair(tmp_path)
    assert not result.passed and result.test is None and result.result_error, asdict(result)
    assert result.container.state == "completed" and result.container.cleanup_complete
    assert (tmp_path / "results/uncorrupted-result.json").exists()
    assert (tmp_path / "results/steps/1/after.json").exists() or relative == "steps/1/after.json"


@pytest.mark.parametrize(
    "code",
    [
        'document["steps"][1].pop("preparation")',
        'document["steps"][1]["preparation"]["ready"] = False',
        'document["steps"][1]["preparation"]["verification"]["complete"] = False',
        'document["steps"][1]["preparation"]["plan"]["deleted_path"] = "wrong.md"',
        'document["steps"][1]["preparation"]["before"] = "steps/0/after.json"',
        'document["steps"][0]["command"]["exit_code"] = 7',
        'document["steps"][1]["command"]["cwd"] = "/different"',
        'document["steps"][1]["command"]["args"] = ["another-command"]',
        'document["steps"][0]["preparation"] = document["steps"][1]["preparation"]',
    ],
)
def test_inconsistent_history_is_reported_by_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    _corrupt_after_run(
        tmp_path, monkeypatch, code + '\n(output / "result.json").write_text(json.dumps(document))'
    )
    result = run_repair(tmp_path)
    assert not result.passed and result.test is None and result.result_error, asdict(result)
    assert "invalid" in result.result_error
    assert (tmp_path / "results/steps/1/preparation/result.json").exists()


@pytest.mark.parametrize(
    "defect",
    ["wrong_binding", "duplicate_entry", "obstacle", "missing_content", "wrong_alteration"],
)
def test_inconsistent_intermediate_proof_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    change = {
        "wrong_binding": 'entry["content_file"] = "steps/0/after/project/other.md"',
        "duplicate_entry": 'snapshot["entries"].append(snapshot["entries"][0])',
        "obstacle": 'snapshot["obstacles"].append({"operation":"read_file", '
        '"root":"project", "path":"x", "reason":"Denied"})',
        "missing_content": 'entry["content_file"] = None',
        "wrong_alteration": '(output / "steps/1/preparation/altered-content.bin")'
        '.write_bytes(b"Wrong witness")',
    }[defect]
    _corrupt_after_run(
        tmp_path,
        monkeypatch,
        'path = output / "steps/1/before.json"\nsnapshot = json.loads(path.read_bytes())\n'
        'entry = next(e for e in snapshot["entries"] if e.get("content_file"))\n'
        + change
        + "\npath.write_text(json.dumps(snapshot))",
    )
    result = run_repair(tmp_path)
    assert not result.passed and result.test is None and result.result_error, asdict(result)
    assert (tmp_path / "results/uncorrupted-result.json").exists()
