"""Two dependent installations through controlled processes and the real verifier."""

import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.reinstall_support import (
    SKILL,
    arrange_reinstall,
    check_retained_snapshots,
    run_reinstall,
)
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.result_reader import read_result


def test_two_installs_share_preparation_and_preserve_distinct_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, "passed", 1)
    result = run_reinstall(tmp_path)
    assert result.passed and result.test is not None
    first, second = result.test.steps
    assert first["command"] is not None and second["command"] is not None
    assert first["command"]["args"] == second["command"]["args"]
    assert first["command"]["cwd"] == second["command"]["cwd"]
    assert (tmp_path / "work/reinstall/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    for index, step in enumerate(result.test.steps):
        assert step["verification"] is not None and step["verification"].complete
        assert not step["verification"].mismatches and not step["verification"].obstacles
        assert f"installation {index}" in (output / f"steps/{index}/stdout.txt").read_text()
    shutil.rmtree(tmp_path / "work/reinstall")
    shutil.rmtree(tmp_path / "subject")
    case = InstallTestCase.from_json((tmp_path / "campaign/inputs/reinstall.json").read_text())
    assert read_result(output, case) == result.test
    check_retained_snapshots(output)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "mode, mismatch",
    [
        ("duplicate_markdown", "section_count"),
        ("duplicate_json", "json_entry_count"),
        ("user_markdown", "user_content_lost"),
        ("user_json", "user_content_lost"),
        ("user_document", "unexpected_change"),
        ("backup", "unexpected_entry"),
        ("skill", "content_mismatch"),
        ("reference", "content_mismatch"),
        ("missing_reference", "missing_file"),
        ("extra_reference", "unexpected_reference"),
        ("home", "unexpected_change"),
        ("project", "unexpected_change"),
        ("nonzero", None),
        ("signal", None),
    ],
)
def test_faults_stop_dependents_and_retain_both_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index: int, mode: str, mismatch: str | None
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, mode, index)
    result = run_reinstall(tmp_path)
    assert not result.passed and result.test is not None and result.result_error is None
    assert result.container.state == "completed" and result.container.cleanup_complete
    assert result.test.status == ("incomplete" if mode == "signal" else "failed")
    step = result.test.steps[index]
    assert step["command"] is not None and step["verification"] is not None
    assert step["verification"].complete
    if mismatch:
        assert mismatch in {m.type for m in step["verification"].mismatches}
    else:
        assert step["command"]["exit_code"] != 0
    assert (tmp_path / "work/reinstall/command-tmp/attempts").read_text() == str(index + 1)
    assert (tmp_path / f"campaign/cases/reinstall/steps/{index}/after.json").exists()
    if index == 0:
        assert result.test.steps[1]["command"] is None
        assert "Step 0" in (result.test.steps[1]["skip_reason"] or "")
        assert not (tmp_path / "campaign/cases/reinstall/steps/1").exists()


def test_version_change_is_compared_to_first_installation_not_package_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, "version", 1)
    result = run_reinstall(tmp_path)
    assert result.test is not None and result.test.status == "failed"
    verification = result.test.steps[1]["verification"]
    assert verification is not None
    assert "version_changed" in {m.type for m in verification.mismatches}
    output = result.output_directory
    assert (
        output / f"steps/0/after/project/{SKILL}.graphify_version"
    ).read_text() == "Any version\n"
    assert (
        output / f"steps/1/after/project/{SKILL}.graphify_version"
    ).read_text() == "Changed version\n"
