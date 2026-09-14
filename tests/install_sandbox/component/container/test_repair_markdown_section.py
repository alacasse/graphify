"""Exercise Markdown repair through a campaign with literal effects and real file checks."""

import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.repair_markdown_section_support import (
    ALTERED,
    CONFORMING,
    MARKDOWN,
    arrange_markdown,
    run_markdown,
)
from tests.install_sandbox.docker.test_repair_markdown_section_docker import check_case
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.result_reader import read_result


def test_repair_and_user_sections_survive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    result = run_markdown(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    check_case(result)
    output = result.output_directory
    assert (tmp_path / "work/repair-markdown-section/command-tmp/attempts").read_text() == "2"
    for phase, expected in [
        ("steps/0/after", CONFORMING),
        ("steps/1/before", ALTERED),
        ("steps/1/after", CONFORMING),
    ]:
        assert (output / phase / "project" / MARKDOWN).read_bytes() == expected.encode()
    assert (output / "steps/1/preparation/altered-content.bin").read_bytes() == ALTERED.encode()
    case = InstallTestCase.from_json(
        (tmp_path / "campaign/inputs/repair-markdown-section.json").read_text()
    )
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case) == result.test


@pytest.mark.parametrize(
    "mode,status,mismatch",
    [
        ("absent", "failed", "content_mismatch"),
        ("wrong_section", "failed", "content_mismatch"),
        ("lost_prefix", "failed", "user_content_lost"),
        ("lost_suffix", "failed", "user_content_lost"),
        ("missing", "failed", "missing_file"),
        ("nonzero", "failed", None),
        ("signal", "incomplete", "content_mismatch"),
        ("timeout", "incomplete", "content_mismatch"),
        ("not_started", "incomplete", "content_mismatch"),
        ("version", "failed", "version_changed"),
        ("home", "failed", "unexpected_change"),
        ("missing_reference", "failed", "missing_file"),
    ],
)
def test_bad_reinstallation_keeps_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, status: str, mismatch: str | None
) -> None:
    arrange_markdown(tmp_path, monkeypatch, mode)
    result = run_markdown(tmp_path)
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
    ["write_failure", "wrong_content", "no_change", "lost_suffix", "extra_change", "unreadable"],
)
def test_bad_preparation_blocks_second_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_MARKDOWN_PREPARATION", mode)
    result = run_markdown(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "incomplete" and not result.passed
    assert (tmp_path / "work/repair-markdown-section/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    assert prep["verification"].complete == (mode != "unreadable")
    assert prep["verification"].obstacles or prep["verification"].mismatches
    if mode == "write_failure":
        assert (
            result.output_directory / "steps/1/before/project" / MARKDOWN
        ).read_bytes() == b"Partial Markdown write\n"


@pytest.mark.parametrize("mode", ["first_failure", "first_loss"])
def test_first_failure_prevents_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_markdown(tmp_path, monkeypatch, mode)
    result = run_markdown(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "failed"
    assert "preparation" not in result.test.steps[1]
    assert not (result.output_directory / "steps/1").exists()


def test_preparation_requires_a_real_section_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_markdown(tmp_path, monkeypatch)
    source = tmp_path / "subject/graphify/always_on/agents-md.md"
    source.write_text("## graphify\nSandbox altered Markdown section.\n")
    executable = tmp_path / "controlled-installer"
    executable.write_text(
        executable.read_text().replace("Use the graph.", "Sandbox altered Markdown section.")
    )
    result = run_markdown(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "incomplete"
    assert result.test.steps[1]["command"] is None
    preparation = result.test.steps[1].get("preparation")
    assert preparation is not None and not preparation["ready"]
    assert "invalid_preparation" in {m.type for m in preparation["verification"].mismatches}
