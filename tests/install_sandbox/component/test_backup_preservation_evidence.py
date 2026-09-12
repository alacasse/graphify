"""Reject absent, misbound or contradictory backup preservation evidence on the host."""

from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_preserve_skill_backup import (
    SKILL,
    arrange_backup,
    run_backup,
)
from tests.install_sandbox.component.test_repair_evidence import corrupt_after_run


def _corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    corrupt_after_run(tmp_path, monkeypatch, code, program_name="controlled_backup_case.py")


@pytest.mark.parametrize(
    "relative",
    [
        "journal.log",
        "preparation.log",
        "expected.json",
        "expected/graphify/skill.md",
        "steps/0/before.json",
        "steps/0/after.json",
        "steps/1/before.json",
        "steps/1/after.json",
        "steps/1/preparation/plan.json",
        "steps/1/preparation/result.json",
        "steps/1/preparation/backup-content.bin",
        "steps/1/verification.json",
        "steps/0/stdout.txt",
        "steps/1/stderr.txt",
        "steps/1/before/project/" + SKILL,
        "steps/1/before/project/" + SKILL + ".bak",
        "steps/1/after/project/" + SKILL + ".bak",
    ],
)
def test_missing_proofs_prevent_host_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    _corrupt(tmp_path, monkeypatch, f"(output / {relative!r}).unlink()")
    result = run_backup(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.state == "completed" and result.container.cleanup_complete
    assert (tmp_path / "campaign/cases/preserve-skill-backup/uncorrupted-result.json").exists()


@pytest.mark.parametrize(
    "code",
    [
        'document["steps"][1].pop("preparation")',
        'document["steps"][1]["preparation"]["ready"] = False',
        'document["steps"][1]["preparation"]["verification"]["complete"] = False',
        'document["steps"][1]["preparation"]["plan"]["backup_path"] = "wrong.md"',
        'document["steps"][1]["preparation"]["before"] = "steps/0/after.json"',
        'document["steps"][0]["command"]["exit_code"] = 7',
        'document["steps"][1]["command"]["cwd"] = "/different"',
        'document["steps"][1]["command"]["args"] = ["another-command"]',
        'document["steps"][0]["preparation"] = document["steps"][1]["preparation"]',
    ],
)
def test_inconsistent_history_prevents_host_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    _corrupt(
        tmp_path, monkeypatch, code + '\n(output / "result.json").write_text(json.dumps(document))'
    )
    result = run_backup(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_backup",
        "wrong_path",
        "deletion_added",
        "backup_digest_only",
        "wrong_binding",
        "missing_backup_content",
        "duplicate_entry",
    ],
)
def test_inconsistent_saved_proofs_prevent_host_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    change = {
        "wrong_backup": '(output / "steps/1/preparation/backup-content.bin")'
        '.write_bytes(b"Wrong witness")',
        "wrong_path": 'plan["backup_path"] = "another-skill.md"',
        "deletion_added": 'plan["deleted_path"] = "another-file.md"',
        "backup_digest_only": 'entry.pop("content_file"); entry["sha256"] = "a" * 64',
        "wrong_binding": f'entry["content_file"] = "steps/1/before/project/{SKILL}"',
        "missing_backup_content": 'entry["content_file"] = None',
        "duplicate_entry": 'snapshot["entries"].append(entry)',
    }[defect]
    _corrupt(
        tmp_path,
        monkeypatch,
        'plan = document["steps"][1]["preparation"]["plan"]\n'
        'path = output / "steps/1/after.json"\nsnapshot = json.loads(path.read_bytes())\n'
        f'entry = next(e for e in snapshot["entries"] if e["path"] == {SKILL + ".bak"!r})\n'
        + change
        + "\npath.write_text(json.dumps(snapshot))\n"
        '(output / "steps/1/preparation/plan.json").write_text(json.dumps(plan))\n'
        '(output / "steps/1/preparation/result.json").write_text('
        'json.dumps(document["steps"][1]["preparation"]))\n'
        '(output / "result.json").write_text(json.dumps(document))',
    )
    result = run_backup(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.cleanup_complete


@pytest.mark.parametrize("entry", [{}, 42])
def test_malformed_preparation_snapshot_is_a_host_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: object
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    _corrupt(
        tmp_path,
        monkeypatch,
        'path = output / "steps/1/before.json"\n'
        "snapshot = json.loads(path.read_bytes())\n"
        f'snapshot["entries"] = [{entry!r}]\n'
        "path.write_text(json.dumps(snapshot))",
    )
    result = run_backup(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.state == "completed" and result.container.cleanup_complete


@pytest.mark.parametrize(
    "phase,path",
    [
        ("steps/0/after", SKILL),
        ("steps/1/before", SKILL),
        ("steps/1/after", SKILL),
        ("steps/1/before", SKILL + ".bak"),
        ("steps/1/after", SKILL + ".bak"),
    ],
)
def test_success_requires_skill_and_backup_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, path: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    _corrupt(
        tmp_path,
        monkeypatch,
        f'snapshot_path = output / "{phase}.json"\n'
        "snapshot = json.loads(snapshot_path.read_bytes())\n"
        f'snapshot["entries"] = [e for e in snapshot["entries"] if e["path"] != {path!r}]\n'
        "snapshot_path.write_text(json.dumps(snapshot))\n"
        f'(output / "{phase}/project/{path}").unlink()',
    )
    result = run_backup(tmp_path)
    assert result.test is None and result.result_error and not result.passed, asdict(result)
    assert result.container.state == "completed" and result.container.cleanup_complete
