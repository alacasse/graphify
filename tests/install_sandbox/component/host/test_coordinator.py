"""Coordinator conduct through controlled commands and real runner verification."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.coordinator_support import arrange_first, run_first
from tools.install_sandbox.contracts.case import InstallTestCase


@pytest.mark.parametrize(
    "mode, preparation_failure, expected",
    [
        ("passed", False, "passed"),
        ("missing", False, "failed"),
        ("nonzero", False, "failed"),
        ("signal", False, "incomplete"),
    ],
)
def test_conduct_keeps_case_status_separate_from_completed_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    preparation_failure: bool,
    expected: str,
) -> None:
    arrange_first(tmp_path, monkeypatch, mode)
    monkeypatch.setenv("CONTROLLED_PREPARATION_FAIL", "1" if preparation_failure else "0")
    result = run_first(tmp_path)
    assert result.container.state == "completed" and result.container.cleanup_complete
    assert result.result_error is None and result.test is not None
    assert result.test.status == expected
    assert result.passed == (expected == "passed")
    case = InstallTestCase.from_json((tmp_path / "campaign/inputs/first-install.json").read_text())
    assert case.target == "sandbox-reference" and case.operations == ["install"]
    shutil.rmtree(tmp_path / "work/first-install")
    shutil.rmtree(tmp_path / "subject")
    assert (result.output_directory / "journal.log").read_text()
    assert json.loads((result.output_directory / "result.json").read_text())["status"] == expected
    if expected == "failed":
        step = result.test.steps[0]
        assert step["command"] is not None and step["verification"] is not None
        assert step["command"]["exit_code"] == (7 if mode == "nonzero" else 0)
        assert bool(step["verification"].mismatches) == (mode == "missing")


@pytest.mark.parametrize("mode", ["container_cleanup_fail", "run_fail"])
def test_valid_passed_case_survives_harness_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_first(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    result = run_first(tmp_path)
    assert result.test is not None and result.test.status == "passed"
    assert result.result_error is None and not result.passed
    assert result.container.state == "incomplete"
    assert result.container.cleanup_complete == (mode == "run_fail")
    assert result.container.detail


@pytest.mark.parametrize(
    "mode, diagnostic", [("success", "unavailable"), ("invalid_result", "invalid")]
)
def test_completed_harness_without_valid_result_is_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    diagnostic: str,
) -> None:
    arrange_first(tmp_path, monkeypatch)
    monkeypatch.delenv("FAKE_DOCKER_CASE_PROGRAM")
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    result = run_first(tmp_path)
    assert result.container.state == "completed"
    assert not result.passed and result.test is None
    assert diagnostic in (result.result_error or "")
    assert (result.output_directory / "journal.log").read_text()


def test_interrupted_harness_preserves_partial_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_first(tmp_path, monkeypatch)
    monkeypatch.delenv("FAKE_DOCKER_CASE_PROGRAM")
    monkeypatch.setenv("FAKE_DOCKER_MODE", "run_interrupt")
    result = run_first(tmp_path)
    assert result.container.state == "interrupted"
    assert result.test is None and not result.passed
    assert "unavailable" in (result.result_error or "")
    assert (result.output_directory / "journal.log").read_text()


def test_unreadable_result_does_not_hide_harness_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_first(tmp_path, monkeypatch)
    original = Path.read_text

    def read(path: Path, *args: object, **kwargs: object) -> str:
        if path == tmp_path / "campaign/cases/first-install/result.json":
            raise PermissionError("Controlled result read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_text", read)
    result = run_first(tmp_path)
    assert result.container.state == "completed" and result.test is None
    assert "unreadable" in (result.result_error or "")
    assert not result.passed
