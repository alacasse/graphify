"""Render supplied duration facts without executing an upstream layer."""

from pathlib import Path

from tests.install_sandbox.component.host.native_support import completed
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.coordinator import CampaignCase, CampaignResult, CoordinatedResult
from tools.install_sandbox.host.timing_reader import CaseTimingResult
from tools.install_sandbox.host.timing_report import render_campaign


def test_report_keeps_container_substeps_out_of_host_total() -> None:
    case = CoordinatedResult(
        completed(),
        None,
        "Result unavailable",
        Path("evidence/reinstall"),
        7.0,
        [Timing("run", state="measured", duration_seconds=5.0)],
        CaseTimingResult([Timing("initial", state="measured", duration_seconds=3.0)], 3.0),
    )
    result = CampaignResult(
        output_directory=Path("evidence"),
        cases=[CampaignCase("reinstall", case.output_directory, result=case, state="finished")],
        duration_seconds=11.0,
        timings=[Timing("build", state="measured", duration_seconds=4.0)],
    )

    report = render_campaign(result)

    assert "Campaign total: 11.000 s" in report
    assert "Passed: False; total: 7.000 s" in report
    assert report.count("Build the image: 4.000 s") == 1
    assert "Run the container and wait for its exit: 5.000 s" in report
    assert "Container details (included in run, never added to totals):" in report
    assert "Prepare and check the initial state: 3.000 s" in report


def test_partial_report_distinguishes_zero_skipped_and_unavailable() -> None:
    internal = CaseTimingResult(
        phases=[
            Timing("initial", state="measured", duration_seconds=0),
            Timing("command", state="running"),
            Timing("checks", state="not_run"),
        ],
        diagnostics=["Interrupted before timing finalization"],
    )
    case = CoordinatedResult(
        completed(), None, None, Path("evidence/reinstall"), container_timings=internal
    )
    result = CampaignResult(
        output_directory=Path("evidence"),
        cases=[CampaignCase("reinstall", case.output_directory, result=case, state="incomplete")],
        interrupted=True,
    )

    report = render_campaign(result)

    assert "Interrupted: True" in report
    assert "Campaign total: unavailable" in report
    assert "Passed: False; total: unavailable" in report
    assert "Prepare and check the initial state: 0.000 s" in report
    assert "Run the installation command: unavailable (started; end not recorded)" in report
    assert "Observe, verify and save evidence: not run" in report
    assert "Timing diagnostic: Interrupted before timing finalization" in report
