"""Duration evidence across real local cases, failures and interrupted persistence."""

import json
import select
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component import test_coordinator as first
from tests.install_sandbox.component import test_reinstall as reinstall
from tests.install_sandbox.component.test_local_runner import LocalCase
from tests.install_sandbox.component.test_preserve_skill_backup import arrange_backup, run_backup
from tests.install_sandbox.component.test_repair_references import arrange_repair, run_repair
from tests.install_sandbox.component.test_repair_skill import arrange_skill, run_skill
from tests.install_sandbox.docker import test_preserve_skill_backup_docker as backup_proof
from tests.install_sandbox.docker import test_reinstall_docker as reinstall_proof
from tests.install_sandbox.docker import test_repair_references_docker as repair_proof
from tests.install_sandbox.docker import test_repair_skill_docker as skill_proof
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import CoordinatedResult
from tools.install_sandbox.driver import command_environment, execute_command
from tools.install_sandbox.results import TestResultWriter as ResultWriter
from tools.install_sandbox.timing_reader import read_timings
from tools.install_sandbox.timing_report import format_duration, render_timings
from tools.install_sandbox.timings import Timing, measure


def _arrange_reinstall(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reinstall.arrange_reinstall(path, monkeypatch, "passed", 1)


@pytest.mark.parametrize(
    "arrange, run",
    [
        (first.arrange_first, first.run_first),
        (_arrange_reinstall, reinstall.run_reinstall),
        (arrange_repair, run_repair),
        (arrange_skill, run_skill),
        (arrange_backup, run_backup),
    ],
    ids=[
        "first-install",
        "reinstall",
        "repair-references",
        "repair-skill",
        "preserve-skill-backup",
    ],
)
def test_five_cases_retain_nonoverlapping_durations_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[Path, pytest.MonkeyPatch], None],
    run: Callable[[Path], CoordinatedResult],
) -> None:
    arrange(tmp_path, monkeypatch)
    result = run(tmp_path)
    assert result.passed and result.test is not None
    assert not result.container_timings.diagnostics
    assert [r.phase for r in result.timings] == [
        "run",
        "cleanup",
        "read",
    ]
    _assert_total(result.duration_seconds, result.timings)
    internal = result.container_timings
    _assert_total(internal.duration_seconds, internal.phases)
    commands = [r for r in internal.phases if r.phase == "command"]
    assert len(commands) == len(result.test.steps)
    assert [r.step for r in commands] == list(range(len(result.test.steps)))
    case = InstallTestCase.from_json(
        (tmp_path / f"campaign/inputs/{result.test.case['name']}.json").read_text()
    )
    assert read_timings(result.output_directory, case) == internal
    assert result.container.cleanup_complete
    checks = {
        "reinstall": reinstall_proof.check_case,
        "repair-references": repair_proof.check_case,
        "repair-skill": skill_proof.check_case,
        "preserve-skill-backup": backup_proof.check_case,
    }
    if result.test.case["name"] in checks:
        checks[result.test.case["name"]](result)
    (tmp_path / "coordinated-result.json").write_text(json.dumps(asdict(result), default=str))
    unmeasured = Timing("additional_checks", state="unavailable")
    (tmp_path / "timing-report.txt").write_text(render_timings(result, unmeasured))


def _assert_total(total: float | None, records: list[Timing]) -> None:
    assert total is not None and total > 0
    assert all(r.state == "measured" and r.duration_seconds is not None for r in records)
    assert sum(r.duration_seconds or 0 for r in records) <= total


@pytest.mark.parametrize("mode", ["nonzero", "not_started", "signal", "timeout", "first_failure"])
def test_command_failures_keep_durations_without_changing_case_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_backup(tmp_path, monkeypatch, mode)
    result = run_backup(tmp_path)
    assert not result.passed and result.test is not None
    assert result.test.status == (
        "failed" if mode in {"nonzero", "first_failure"} else "incomplete"
    )
    assert result.container.cleanup_complete
    assert not result.container_timings.diagnostics
    index = 0 if mode == "first_failure" else 1
    commands = [r for r in result.container_timings.phases if r.phase == "command"]
    assert commands[index].state == "measured"
    assert commands[index].duration_seconds is not None
    if mode == "first_failure":
        assert commands[1].state == "not_run" and commands[1].duration_seconds is None


def test_writer_failure_does_not_change_business_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    replace = Path.replace

    def fail_timing(path: Path, target: Path) -> Path:
        if path.name == "timings.json.tmp":
            raise PermissionError("Controlled timing write refusal")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_timing)
    result = LocalCase(tmp_path).run()
    assert result.status == "passed"
    assert (tmp_path / "results/result.json").is_file()
    assert "Timing evidence unavailable" in capsys.readouterr().err
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    assert read_timings(tmp_path / "results", case).diagnostics


def test_progress_writes_are_outside_phase_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = [0]
    monkeypatch.setattr(time, "monotonic_ns", lambda: ticks[0])
    writer = ResultWriter(tmp_path)
    writer.initialize_timings("first-install", 1)
    replace_file = Path.replace

    def slow_write(path: Path, target: Path) -> Path:
        ticks[0] += 1_000_000_000
        return replace_file(path, target)

    monkeypatch.setattr(Path, "replace", slow_write)
    with writer.measure("initial"):
        assert (
            json.loads((tmp_path / "timings.json").read_text())["phases"][0]["state"] == "running"
        )
        ticks[0] += 2_000_000_000
    writer.finish_timings(0)
    data = json.loads((tmp_path / "timings.json").read_text())
    assert data["phases"][0]["duration_seconds"] == 2.0
    assert data["duration_seconds"] == 4.0
    assert ticks[0] == 5_000_000_000  # Last timing write cannot measure itself.


def test_driver_uses_monotonic_elapsed_for_real_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([10_000_000_000, 12_250_000_000])
    monkeypatch.setattr(time, "monotonic_ns", lambda: next(ticks))
    result = execute_command(
        [sys.executable, "-c", "print('done')"],
        tmp_path,
        command_environment(tmp_path, tmp_path),
        5,
    )
    assert result.exit_code == 0 and result.stdout == b"done\n"
    assert result.duration_seconds == 2.25


def test_killed_process_leaves_completed_and_running_phases(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    script = (
        "import sys, time\nfrom pathlib import Path\n"
        "from tools.install_sandbox.results import TestResultWriter\n"
        "w = TestResultWriter(Path(sys.argv[1]))\n"
        "w.initialize_timings('first-install', 1)\n"
        "with w.measure('initial'): pass\n"
        "with w.measure('command', 0):\n"
        "    print('ready', flush=True)\n    time.sleep(60)\n"
    )
    output = local.root / "results"
    with subprocess.Popen(
        [sys.executable, "-c", script, str(output)], stdout=subprocess.PIPE
    ) as process:
        try:
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 5)[0]
            assert process.stdout.readline() == b"ready\n"
        finally:
            process.kill()
            process.communicate(timeout=5)
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    result = read_timings(output, case)
    assert result.duration_seconds is None and result.diagnostics
    assert result.phases[0].state == "measured"
    assert result.phases[1].state == "running" and result.phases[1].duration_seconds is None
    assert result.phases[2].state == "pending"


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


def test_phase_exception_retains_duration_without_swallowing_error() -> None:
    record = Timing("command", 0)
    with pytest.raises(RuntimeError, match="Controlled failure"), measure(record):
        raise RuntimeError("Controlled failure")
    assert record.state == "measured" and record.duration_seconds is not None
    assert record.diagnostic == "Operation raised RuntimeError"


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
