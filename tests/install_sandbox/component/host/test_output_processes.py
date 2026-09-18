"""Real local processes prove lock release, signal ownership and crash observation."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.output_support import START, refused
from tools.install_sandbox.host import output_retention
from tools.install_sandbox.host.output_report import Writer, read_report


def _wait_file(path: Path, process: subprocess.Popen[str]) -> None:
    end = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None, process.communicate(timeout=2)
        assert time.monotonic() < end, f"Timed out waiting for {path}"
        time.sleep(0.01)


def _child(root: Path, body: str) -> subprocess.Popen[str]:
    script = root / "child.py"
    script.write_text(
        "from datetime import datetime\nfrom pathlib import Path\n"
        "import json, os, signal, sys\n"
        "from tools.install_sandbox.host.output_lifecycle import CampaignOutput\n"
        "from tools.install_sandbox.host.coordinator import InstallTestCoordinator\n"
        "from tools.install_sandbox.host import output_lifecycle\n"
        f"root=Path({str(root)!r})\n" + body + "\nresult=CampaignOutput(managed_root=root/'out', "
        f"now=lambda:datetime.fromisoformat({START.isoformat()!r})).run("
        "specs_directory=root/'specs', target='missing', subject_checkout=root/'subject')\n"
        "print(result.report.render(), flush=True)\n"
        "raise SystemExit(result.exit_code)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", f"exec(compile(open({str(script)!r}).read(), 'child.py', 'exec'))"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_abrupt_process_loss_uses_first_confirmed_stop(tmp_path: Path) -> None:
    (tmp_path / "subject").mkdir()
    body = (
        "def crash(*args, **kwargs):\n    os._exit(7)\nInstallTestCoordinator.run_campaign=crash\n"
    )
    with _child(tmp_path, body) as process:
        process.communicate(timeout=10)
        assert process.returncode == 7
    old = next((tmp_path / "out/in-progress").iterdir())
    assert read_report(old, tmp_path / "out").finished_at is None
    observed = START + timedelta(days=30)
    refused(tmp_path, observed)
    report = read_report(old, tmp_path / "out")
    assert report.stopped_observed_at == observed.isoformat()
    assert report.phase == "allocated" and report.archive == "absent"
    refused(tmp_path, observed + timedelta(days=14))
    assert not old.exists()


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("phase", ["before_execution", "archive"])
def test_real_signals_cover_the_whole_user_path(
    tmp_path: Path, number: signal.Signals, phase: str
) -> None:
    (tmp_path / "subject").mkdir()
    if phase == "before_execution":
        body = (
            "def wait_for_signal(*args, **kwargs):\n"
            "    (root/'ready').touch()\n"
            "    kwargs['interrupts'].event.wait(10)\n"
            "    raise InterruptedError('interrupted before first result')\n"
            "InstallTestCoordinator.run_campaign=wait_for_signal\n"
        )
    else:
        body = (
            "archive=output_lifecycle.archive_evidence\n"
            "def wait_for_signal(directory, interrupts):\n"
            "    (root/'ready').touch()\n"
            "    interrupts.event.wait(10)\n"
            "    archive(directory, interrupts)\n"
            "output_lifecycle.archive_evidence=wait_for_signal\n"
        )
    with _child(tmp_path, body) as process:
        _wait_file(tmp_path / "ready", process)
        os.kill(process.pid, number)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + number, stdout + stderr
    directory = next((tmp_path / "out/in-progress").iterdir())
    report = read_report(directory, tmp_path / "out")
    assert report.exit_code == 128 + number
    assert report.writers == [] and not (directory / "evidence.zip").exists()


def test_inspection_releases_global_lock_and_revalidates_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = refused(tmp_path).output_directory
    assert old is not None
    report = read_report(old, tmp_path / "out")
    report.writers = [Writer("owned", "run", "docker", "daemon", "returned")]
    report.save(old)
    inspections: list[bool] = []

    def inspect(*args: object) -> bool:
        code = (
            "from pathlib import Path; "
            "from tools.install_sandbox.host.output_storage import coordination; "
            f"lock=coordination(Path({str(tmp_path / 'out')!r})); "
            "lock.__enter__(); lock.__exit__(None,None,None)"
        )
        child = subprocess.run([sys.executable, "-c", code], timeout=5, check=False)
        assert child.returncode == 0
        changed = read_report(old, tmp_path / "out")
        changed.phase = "changed-during-inspection"
        changed.save(old)
        inspections.append(True)
        return True

    monkeypatch.setattr(output_retention, "writer_stopped", inspect)
    result = refused(tmp_path, START + timedelta(days=20))
    assert inspections == [True] and old.exists()
    assert "changed during inspection" in result.report.render()


def test_terminal_container_without_restart_allows_stable_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.install_sandbox.component.host.output_support import RUNTIME
    from tools.install_sandbox.host.docker_runtime import runtime_identity

    old = refused(tmp_path).output_directory
    assert old is not None
    report = read_report(old, tmp_path / "out")
    report.finished_at = None
    report.writers = [Writer("owned", "run", runtime_identity(str(RUNTIME)), "daemon")]
    report.save(old)

    def query(runtime: str, arguments: list[str]) -> str:
        if arguments[0] == "info":
            return "daemon"
        if arguments[0] == "container":
            return "owned-id"
        return json.dumps(
            [
                {
                    "Name": "/owned",
                    "State": {
                        "Status": "exited",
                        "Running": False,
                        "Restarting": False,
                        "Paused": False,
                    },
                    "HostConfig": {"RestartPolicy": {"Name": "no"}},
                }
            ]
        )

    monkeypatch.setattr(output_retention, "_runtime_query", query)
    refused(tmp_path, START + timedelta(days=20))
    assert read_report(old, tmp_path / "out").stopped_observed_at is not None
