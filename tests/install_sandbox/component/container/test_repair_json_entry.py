"""Prove registration restoration and personal preservation through real filesystem effects."""

import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.repair_json_entry_support import (
    SETTINGS,
    arrange_json,
    run_json,
)
from tests.install_sandbox.docker.test_repair_json_entry_docker import check_case
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize("preparation", ["passed", "format"])
def test_repair_and_personal_values_survive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preparation: str
) -> None:
    arrange_json(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_JSON_PREPARATION", preparation)
    result = run_json(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    check_case(result)
    assert (tmp_path / "work/repair-json-entry/command-tmp/attempts").read_text() == "2"
    case = InstallTestCase.from_json(
        (tmp_path / "campaign/inputs/repair-json-entry.json").read_text()
    )
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(result.output_directory, case) == result.test
    check_case(result)


@pytest.mark.parametrize(
    "mode,status,mismatch",
    [
        ("absent", "failed", "json_entry_count"),
        ("duplicate", "failed", "json_entry_count"),
        ("reverse", "failed", "user_content_lost"),
        ("theme", "failed", "user_content_lost"),
        ("lost_personal", "failed", "user_content_lost"),
        ("personal_file", "failed", "unexpected_change"),
        ("missing", "failed", "missing_file"),
        ("invalid", "failed", "invalid_json"),
        ("nonzero", "failed", None),
        ("signal", "incomplete", "json_entry_count"),
        ("timeout", "incomplete", "json_entry_count"),
        ("not_started", "incomplete", "json_entry_count"),
        ("version", "failed", "version_changed"),
        ("home", "failed", "unexpected_change"),
        ("missing_reference", "failed", "missing_file"),
    ],
)
def test_bad_reinstallation_keeps_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, status: str, mismatch: str | None
) -> None:
    arrange_json(tmp_path, monkeypatch, mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    verification = result.test.steps[1]["verification"]
    assert verification is not None and verification.complete
    if mismatch:
        assert mismatch in {m.type for m in verification.mismatches}
    else:
        assert not verification.mismatches
    assert (result.output_directory / "steps/1/after.json").exists()


@pytest.mark.parametrize(
    "mode",
    [
        "write_failure",
        "invalid",
        "no_change",
        "wrong_entry",
        "reverse",
        "theme",
        "extra_change",
        "hooks",
        "hook_extra",
        "read_failure",
        "unreadable",
    ],
)
def test_bad_preparation_blocks_second_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_json(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_JSON_PREPARATION", mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "incomplete" and not result.passed
    assert (tmp_path / "work/repair-json-entry/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    assert prep["verification"].complete == (mode not in {"unreadable", "read_failure"})
    assert prep["verification"].obstacles or prep["verification"].mismatches
    if mode == "write_failure":
        assert (
            result.output_directory / "steps/1/before/project" / SETTINGS
        ).read_bytes() == b'{"theme":'


@pytest.mark.parametrize("mode", ["first_failure", "first_loss"])
def test_first_failure_prevents_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_json(tmp_path, monkeypatch, mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "failed"
    assert "preparation" not in result.test.steps[1]
    assert not (result.output_directory / "steps/1").exists()
