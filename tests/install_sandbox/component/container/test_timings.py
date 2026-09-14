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

from tests.install_sandbox.component.container import reinstall_support as reinstall
from tests.install_sandbox.component.container.local_case import LocalCase
from tests.install_sandbox.component.container.preserve_skill_backup_support import (
    arrange_backup,
    run_backup,
)
from tests.install_sandbox.component.container.repair_references_support import (
    arrange_repair,
    run_repair,
)
from tests.install_sandbox.component.container.repair_skill_support import arrange_skill, run_skill
from tests.install_sandbox.component.container.timings_support import (
    arrange_reinstall,
    assert_total,
)
from tests.install_sandbox.component.host import coordinator_support as first
from tests.install_sandbox.docker import test_preserve_skill_backup_docker as backup_proof
from tests.install_sandbox.docker import test_reinstall_docker as reinstall_proof
from tests.install_sandbox.docker import test_repair_references_docker as repair_proof
from tests.install_sandbox.docker import test_repair_skill_docker as skill_proof
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter
from tools.install_sandbox.container.installer import command_environment, execute_command
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.coordinator import CoordinatedResult
from tools.install_sandbox.host.timing_reader import read_timings
from tools.install_sandbox.host.timing_report import render_timings


@pytest.mark.parametrize(
    "arrange, run",
    [
        (first.arrange_first, first.run_first),
        (arrange_reinstall, reinstall.run_reinstall),
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
    assert_total(result.duration_seconds, result.timings)
    internal = result.container_timings
    assert_total(internal.duration_seconds, internal.phases)
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
        "from tools.install_sandbox.container.evidence_writer import TestResultWriter\n"
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
