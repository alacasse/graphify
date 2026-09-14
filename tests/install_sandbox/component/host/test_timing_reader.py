"""Verify sandbox behavior at its owning boundary."""

import json
import time
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase
from tests.install_sandbox.component.host import coordinator_support as first
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.timing_reader import read_timings
from tools.install_sandbox.host.timing_report import format_duration, render_timings


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), float("inf"), "1.0"])
def test_invalid_measured_duration_is_optional_diagnostic(tmp_path: Path, bad: object) -> None:
    LocalCase(tmp_path).run()
    path = tmp_path / "results/timings.json"
    data = json.loads(path.read_text())
    data["phases"][0]["duration_seconds"] = bad
    path.write_text(json.dumps(data))
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    result = read_timings(path.parent, case)
    assert result.diagnostics and not result.phases


def test_coordinator_does_not_fail_for_missing_timing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first.arrange_first(tmp_path, monkeypatch)
    read = Path.read_text

    def missing(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.name == "timings.json":
            raise FileNotFoundError("Controlled missing timing evidence")
        return read(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", missing)
    result = first.run_first(tmp_path)
    assert result.passed and result.result_error is None
    assert result.container_timings.diagnostics


@pytest.mark.parametrize(
    "seconds, expected",
    [(None, "unavailable"), (0, "0.000 s"), (0.0001, "< 0.001 s"), (1.2345, "1.234 s")],
)
def test_duration_presentation(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_total_includes_both_result_and_timing_evidence_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first.arrange_first(tmp_path, monkeypatch)
    ticks = [0]
    read = Path.read_text
    monkeypatch.setattr(time, "monotonic_ns", lambda: ticks[0])

    def read_evidence(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == tmp_path / "campaign/cases/first-install/result.json":
            ticks[0] += 3_000_000_000
        if path == tmp_path / "campaign/cases/first-install/timings.json":
            ticks[0] += 500_000_000
        return read(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_evidence)
    result = first.run_first(tmp_path)
    assert result.passed and result.duration_seconds == 3.5
    assert result.timings[-1].phase == "read"
    assert result.timings[-1].duration_seconds == 3.5


@pytest.mark.parametrize(
    "payload",
    [
        '{"version":1,"version":1,"duration_seconds":null,"phases":[]}',
        '{"version":2,"duration_seconds":null,"phases":[]}',
        '{"version":1,"duration_seconds":null,"phases":[{}]}',
        '{"version":1,"duration_seconds":null,"phases":null}',
        '{"version":1',
    ],
)
def test_malformed_timing_file_does_not_escape_reader(tmp_path: Path, payload: str) -> None:
    LocalCase(tmp_path)
    (tmp_path / "timings.json").write_text(payload)
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    assert read_timings(tmp_path, case).diagnostics


def test_report_keeps_container_substeps_out_of_host_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first.arrange_first(tmp_path, monkeypatch)
    result = first.run_first(tmp_path)
    checks = Timing("additional_checks", state="measured", duration_seconds=2.0)
    report = render_timings(result, checks)
    assert f"Coordinator total: {format_duration(result.duration_seconds)}" in report
    assert "included in container execution, never added to the host total" in report
    assert "Additional test checks: 2.000 s" in report
    assert "startup and exit are not individually measured" in report
