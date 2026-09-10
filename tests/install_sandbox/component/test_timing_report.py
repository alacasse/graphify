"""Proof summaries retain separate additional-check durations, including failed checks."""

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tests.install_sandbox.component import test_coordinator as first
from tests.install_sandbox.docker import test_first_install_docker as proof
from tools.install_sandbox.coordinator import CoordinatedResult
from tools.install_sandbox.timing_reader import CaseTimingResult
from tools.install_sandbox.timing_report import render_timings
from tools.install_sandbox.timings import Timing


@pytest.mark.parametrize("fail", [False, True])
def test_helper_measures_shared_and_case_checks_and_always_saves_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    first.arrange_first(tmp_path, monkeypatch)
    result = replace(first.run_first(tmp_path), duration_seconds=7.0)
    ticks = [0]
    monkeypatch.setattr(time, "monotonic_ns", lambda: ticks[0])
    monkeypatch.setenv("INSTALL_SANDBOX_SUBJECT", str(tmp_path / "subject"))
    directory = tmp_path / "proof"
    monkeypatch.setenv("INSTALL_SANDBOX_EVIDENCE_DIRECTORY", str(directory))

    def coordinated(*args: object, **kwargs: object) -> CoordinatedResult:
        return result

    def runtime(directory: Path) -> Path:
        ticks[0] += 10_000_000_000  # Setup is outside both reported intervals.
        return directory / "unused-runtime"

    monkeypatch.setattr(proof.InstallTestCoordinator, "run_case", coordinated)
    monkeypatch.setattr(proof, "_runtime", runtime)

    def shared(*args: object) -> None:
        ticks[0] += 1_000_000_000

    for name in ("_assert_execution", "_assert_owned_cleanup", "_assert_saved_evidence"):
        monkeypatch.setattr(proof, name, shared)

    def specific(received: CoordinatedResult) -> None:
        assert received is result
        ticks[0] += 2_000_000_000
        if fail:
            raise AssertionError("Controlled case check failure")

    if fail:
        with pytest.raises(AssertionError, match="Controlled case check failure"):
            proof.run_proof("first-install", specific)
    else:
        assert proof.run_proof("first-install", specific) is result
    _assert_report(directory, fail)


def _assert_report(directory: Path, failed: bool) -> None:
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["duration_seconds"] == 7.0
    checks = summary["additional_checks"]
    assert checks["duration_seconds"] == 5.0
    assert checks["diagnostic"] == ("Operation raised AssertionError" if failed else None)
    report = (directory / "summary.txt").read_text()
    assert "Coordinator total: 7.000 s" in report
    assert "Additional test checks: 5.000 s" in report


def test_partial_report_distinguishes_zero_skipped_and_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first.arrange_first(tmp_path, monkeypatch)
    internal = CaseTimingResult(
        phases=[
            Timing("copy_sources", state="measured", duration_seconds=0),
            Timing("venv", state="running"),
            Timing("pip", state="not_run"),
        ],
        diagnostics=["Interrupted before timing finalization"],
    )
    result = replace(first.run_first(tmp_path), container_timings=internal)
    report = render_timings(result, Timing("additional_checks", state="not_run"))
    assert "Copy product sources: 0.000 s" in report
    assert "Create the Python environment: unavailable (started; end not recorded)" in report
    assert "Install the package and dependencies: not run" in report
    assert "Container work not detailed: unavailable" in report
    assert "Timing evidence: incomplete" in report
