"""Reference repair through the coordinator, controlled processes and real verification."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.repair_references_support import (
    REFS,
    SECOND,
    SOURCE,
    THIRD,
    arrange_repair,
    read,
    run_repair,
)


def test_repair_preserves_three_distinct_states_and_sources_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    source_before = {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    result = run_repair(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    assert source_before == {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    assert (tmp_path / "work/repair-references/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    first, second = result.test.steps
    assert first["command"] is not None and second["command"] is not None
    assert first["command"]["args"] == second["command"]["args"]
    assert first["command"]["cwd"] == second["command"]["cwd"]
    prep = second.get("preparation")
    assert prep is not None and prep["ready"]
    assert "deleted_path" in prep["plan"]
    assert prep["plan"]["deleted_path"] == REFS + "one.md"
    assert prep["plan"]["altered_path"] == REFS + "sub/two.md"
    for phase in ("steps/0/after", "steps/1/before", "steps/1/after"):
        altered = (output / phase / "project" / REFS / "sub/two.md").read_bytes()
        assert altered == SECOND + (
            b"\nSandbox repair witness.\n" if phase.endswith("before") else b""
        )
        assert (output / phase / "project" / REFS / "z.md").read_bytes() == THIRD
    before = json.loads((output / "steps/1/before.json").read_bytes())
    assert not any(e["path"] == REFS + "one.md" for e in before["entries"])
    assert (output / "expected" / SOURCE / "sub/two.md").read_bytes() == SECOND
    shutil.rmtree(tmp_path / "work/repair-references")
    shutil.rmtree(tmp_path / "subject")
    assert read(tmp_path) == result.test


@pytest.mark.parametrize(
    "mode, status, mismatch",
    [
        ("absent", "failed", "missing_file"),
        ("partial_deleted", "failed", "content_mismatch"),
        ("partial_altered", "failed", "missing_file"),
        ("nonzero", "failed", "missing_file"),
        ("signal", "incomplete", "missing_file"),
        ("timeout", "incomplete", "missing_file"),
        ("not_started", "incomplete", "missing_file"),
        ("version", "failed", "version_changed"),
        ("backup", "failed", "unexpected_entry"),
        ("home", "failed", "unexpected_change"),
        ("extra_reference", "failed", "unexpected_reference"),
    ],
)
def test_incorrect_or_interrupted_repair_retains_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    mismatch: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch, mode)
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    step = result.test.steps[1]
    verification = step["verification"]
    assert verification is not None and verification.complete
    assert mismatch in {m.type for m in verification.mismatches}
    assert (tmp_path / "campaign/cases/repair-references/steps/1/after.json").exists()
    assert read(tmp_path) == result.test


@pytest.mark.parametrize(
    "mode",
    [
        "delete_failure",
        "write_failure",
        "wrong_content",
        "no_delete",
        "extra_change",
        "extra_reference",
        "unreadable",
    ],
)
def test_preparation_failure_stops_repair_and_retains_partial_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_REPAIR_PREPARATION", mode)
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "incomplete" and not result.passed
    assert (tmp_path / "work/repair-references/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None and step["observations"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    verification = prep["verification"]
    assert verification.obstacles if mode == "unreadable" else verification.mismatches
    assert verification.complete == (mode != "unreadable")
    assert (tmp_path / "campaign/cases/repair-references/steps/1/before.json").exists()
    assert not (tmp_path / "campaign/cases/repair-references/steps/1/stdout.txt").exists()
    if mode == "write_failure":
        assert (
            tmp_path
            / "campaign/cases/repair-references/steps/1/before/project"
            / REFS
            / "sub/two.md"
        ).read_bytes() == b"Partial preparation write\n"
    assert read(tmp_path) == result.test


@pytest.mark.parametrize("count", [0, 1])
def test_insufficient_sources_prevents_both_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    sources = tmp_path / "subject" / SOURCE
    shutil.rmtree(sources / "sub")
    (sources / "z.md").unlink()
    if count == 0:
        (sources / "one.md").unlink()
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None
    assert result.test.status == "not_run"
    assert "at least two" in (result.test.preparation["reason"] or "")
    assert not (tmp_path / "work/repair-references/command-tmp/attempts").exists()
    assert all(s["command"] is None and s["skip_reason"] for s in result.test.steps)


def test_first_failure_prevents_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_repair(tmp_path, monkeypatch, "first_failure")
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None
    assert result.test.status == "failed"
    assert "preparation" not in result.test.steps[1]
    assert not (tmp_path / "campaign/cases/repair-references/steps/1").exists()
    assert result.test.steps[1]["skip_reason"]
