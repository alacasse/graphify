"""Render supplied duration facts without executing an upstream layer."""

from pathlib import Path

from tests.install_sandbox.component.host.native_support import completed
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.coordinator import CoordinatedResult
from tools.install_sandbox.host.timing_reader import CaseTimingResult
from tools.install_sandbox.host.timing_report import render_timings


def test_report_keeps_container_substeps_out_of_host_total() -> None:
    result = CoordinatedResult(
        completed(),
        None,
        "Result unavailable",
        Path("evidence"),
        7.0,
        [Timing("run", state="measured", duration_seconds=5.0)],
        CaseTimingResult([Timing("initial", state="measured", duration_seconds=3.0)], 3.0),
    )
    report = render_timings(
        result, Timing("additional_checks", state="measured", duration_seconds=2.0)
    )
    assert "Coordinator total: 7.000 s" in report
    assert "Host time not detailed: 2.000 s" in report
    assert "included in container execution, never added to the host total" in report
    assert "Measured container work: 3.000 s" in report
    assert "Additional test checks: 2.000 s" in report
    assert "startup and exit are not individually measured" in report


def test_partial_report_distinguishes_zero_skipped_and_unavailable() -> None:
    internal = CaseTimingResult(
        phases=[
            Timing("initial", state="measured", duration_seconds=0),
            Timing("command", state="running"),
            Timing("checks", state="not_run"),
        ],
        diagnostics=["Interrupted before timing finalization"],
    )
    result = CoordinatedResult(
        completed(), None, None, Path("evidence"), container_timings=internal
    )
    report = render_timings(result, Timing("additional_checks", state="not_run"))
    assert "Prepare and check the initial state: 0.000 s" in report
    assert "Run the installation command: unavailable (started; end not recorded)" in report
    assert "Observe, verify and save evidence: not run" in report
    assert "Container work not detailed: unavailable" in report
    assert "Timing evidence: incomplete" in report
