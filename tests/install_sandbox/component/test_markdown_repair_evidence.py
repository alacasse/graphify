"""Reject missing shared-document proofs and contradictory preparation transport."""

from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_repair_evidence import corrupt_after_run
from tests.install_sandbox.component.test_repair_markdown_section import (
    MARKDOWN,
    arrange_markdown,
    run_markdown,
)


def _corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    corrupt_after_run(
        tmp_path, monkeypatch, code, program_name="controlled_markdown_repair_case.py"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "expected.json",
        "expected/graphify/always_on/agents-md.md",
        "steps/0/after.json",
        "steps/1/before.json",
        "steps/1/after.json",
        "steps/1/preparation/plan.json",
        "steps/1/preparation/result.json",
        "steps/1/preparation/altered-content.bin",
        "steps/1/verification.json",
        "steps/1/stdout.txt",
        "steps/0/after/project/" + MARKDOWN,
        "steps/1/before/project/" + MARKDOWN,
        "steps/1/after/project/" + MARKDOWN,
    ],
)
def test_missing_proof_prevents_host_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    _corrupt(tmp_path, monkeypatch, f"(output / {relative!r}).unlink()")
    result = run_markdown(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.state == "completed" and result.container.cleanup_complete


@pytest.mark.parametrize(
    "change",
    [
        'document["steps"][1].pop("preparation")',
        'document["steps"][1]["preparation"]["ready"] = False',
        'document["steps"][0]["command"]["exit_code"] = 7',
        'document["steps"][1]["command"]["args"] = ["other-command"]',
        'document["steps"][1]["preparation"]["before"] = "steps/0/after.json"',
    ],
)
def test_inconsistent_history_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    _corrupt(
        tmp_path,
        monkeypatch,
        change + '\n(output / "result.json").write_text(json.dumps(document))',
    )
    result = run_markdown(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)


@pytest.mark.parametrize(
    "defect", ["path", "deletion", "witness", "binding", "digest", "malformed"]
)
def test_matching_saved_documents_do_not_hide_invalid_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    change = {
        "path": 'plan["altered_path"] = "other.md"',
        "deletion": 'plan["deleted_path"] = "other.md"',
        "witness": '(output / "steps/1/preparation/altered-content.bin")'
        '.write_bytes(b"Wrong witness")',
        "binding": f'entry["content_file"] = "steps/0/after/project/{MARKDOWN}"',
        "digest": 'entry.pop("content_file"); entry["sha256"] = "a" * 64',
        "malformed": 'snapshot["entries"].append(42)',
    }[defect]
    _corrupt(
        tmp_path,
        monkeypatch,
        'plan = document["steps"][1]["preparation"]["plan"]\n'
        'path = output / "steps/1/before.json"\nsnapshot = json.loads(path.read_bytes())\n'
        f'entry = next(e for e in snapshot["entries"] if e["path"] == {MARKDOWN!r})\n'
        + change
        + "\npath.write_text(json.dumps(snapshot))\n"
        '(output / "steps/1/preparation/plan.json").write_text(json.dumps(plan))\n'
        '(output / "steps/1/preparation/result.json").write_text('
        'json.dumps(document["steps"][1]["preparation"]))\n'
        '(output / "result.json").write_text(json.dumps(document))',
    )
    result = run_markdown(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.cleanup_complete
