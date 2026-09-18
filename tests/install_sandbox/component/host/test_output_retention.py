"""Retention starts at a reliable end or a stable confirmed-stop observation."""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.output_support import RUNTIME, START, refused, valid
from tools.install_sandbox.host import output_retention
from tools.install_sandbox.host.docker_runtime import runtime_identity
from tools.install_sandbox.host.output_report import read_report


@pytest.mark.parametrize("age", [14 * 86400 - 1, 14 * 86400, 14 * 86400 + 1, -60])
@pytest.mark.parametrize("nested", [False, True])
def test_expiration_uses_end_at_fourteen_days(tmp_path: Path, age: int, nested: bool) -> None:
    output = tmp_path / "out/group/chosen" if nested else None
    old = refused(tmp_path, output=output).output_directory
    assert old is not None
    new = refused(tmp_path, START + timedelta(seconds=age))
    assert new.output_directory is not None
    assert old.exists() == (age < 14 * 86400)


def test_expired_result_stays_until_current_execution_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = refused(tmp_path).output_directory
    assert old is not None
    original = output_retention.retain_finished
    observations: list[bool] = []

    def cleanup(*args: object, **kwargs: object) -> list[str]:
        observations.append(old.exists())
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("tools.install_sandbox.host.output_lifecycle.retain_finished", cleanup)
    result = refused(tmp_path, START + timedelta(days=14))
    assert result.exit_code == 2 and observations == [True]
    assert not old.exists()


def test_crash_observation_is_not_reset_on_later_passes(tmp_path: Path) -> None:
    old = refused(tmp_path).output_directory
    assert old is not None
    report = read_report(old, tmp_path / "out")
    report.finished_at = None
    report.phase = "running"
    report.save(old)
    observed = START + timedelta(days=30)
    refused(tmp_path, observed)
    assert old.exists()
    assert read_report(old, tmp_path / "out").stopped_observed_at == observed.isoformat()
    refused(tmp_path, observed + timedelta(days=13))
    assert read_report(old, tmp_path / "out").stopped_observed_at == observed.isoformat()
    refused(tmp_path, observed + timedelta(days=14))
    assert not old.exists()


@pytest.mark.parametrize("writer_state", ["intent", "returned", "stopped"])
def test_absent_container_does_not_resolve_unfinished_launch_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer_state: str
) -> None:
    from tools.install_sandbox.host.output_report import Writer

    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    old = refused(tmp_path).output_directory
    assert old is not None
    report = read_report(old, tmp_path / "out")
    report.finished_at = None
    report.writers = [
        Writer(
            "owned-writer", "run", runtime_identity(str(RUNTIME)), "controlled-daemon", writer_state
        )
    ]
    report.save(old)
    result = refused(tmp_path, START + timedelta(days=20))
    saved = read_report(old, tmp_path / "out")
    assert (saved.stopped_observed_at is None) == (writer_state == "intent")
    assert any("uncertain" in d for d in result.report.diagnostics) == (writer_state == "intent")


@pytest.mark.parametrize("activity", ["running", "restart", "daemon", "unreachable"])
def test_uncertain_or_active_writer_preserves_old_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, activity: str
) -> None:
    from tools.install_sandbox.host.output_report import Writer

    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    old = refused(tmp_path).output_directory
    assert old is not None
    report = read_report(old, tmp_path / "out")
    report.finished_at = None
    report.writers = [
        Writer(
            "owned-writer", "run", runtime_identity(str(RUNTIME)), "controlled-daemon", "returned"
        )
    ]
    report.save(old)

    def inspect(runtime: str, arguments: list[str]) -> str:
        if activity == "unreachable":
            raise OSError("runtime unreachable")
        if arguments[0] == "info":
            return "other-daemon" if activity == "daemon" else "controlled-daemon"
        if arguments[0] == "container":
            return "owned-id"
        return json.dumps(
            [
                {
                    "Name": "/owned-writer",
                    "State": {
                        "Status": "running" if activity == "running" else "exited",
                        "Running": activity == "running",
                        "Restarting": False,
                        "Paused": False,
                    },
                    "HostConfig": {
                        "RestartPolicy": {"Name": "always" if activity == "restart" else "no"}
                    },
                }
            ]
        )

    monkeypatch.setattr(output_retention, "_runtime_query", inspect)
    result = refused(tmp_path, START + timedelta(days=20))
    assert old.exists() and read_report(old, tmp_path / "out").stopped_observed_at is None
    assert result.report.diagnostics


def test_active_process_lock_protects_expired_result(tmp_path: Path) -> None:
    old = refused(tmp_path).output_directory
    assert old is not None
    code = (
        "from pathlib import Path; import sys; "
        "from tools.install_sandbox.host.output_storage import FileLock; "
        "lock=FileLock(Path(sys.argv[1])); lock.acquire(); "
        "print('ready', flush=True); sys.stdin.readline(); lock.close()"
    )
    with subprocess.Popen(
        [sys.executable, "-c", code, str(old / ".active.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout is not None and process.stdout.readline().strip() == "ready"
        refused(tmp_path, START + timedelta(days=20))
        assert old.exists()
        process.communicate("release\n", timeout=10)
    refused(tmp_path, START + timedelta(days=20))
    assert not old.exists()


def test_old_cleanup_failure_warns_and_retries_without_changing_current_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = refused(tmp_path, START - timedelta(days=15)).output_directory
    assert old is not None
    remove = Path.unlink

    def denied(path: Path, missing_ok: bool = False) -> None:
        if path == old / "evidence.zip":
            raise PermissionError("controlled old deletion failure")
        remove(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", denied)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code == 0 and old.exists()
    assert "controlled old deletion failure" in result.report.render()
    assert (old / "campaign.json").is_file()
    monkeypatch.setattr(Path, "unlink", remove)
    refused(tmp_path)
    assert not old.exists()


def test_external_output_is_not_adopted_by_retention(tmp_path: Path) -> None:
    external = refused(tmp_path, output=tmp_path / "external").output_directory
    assert external is not None
    refused(tmp_path, START + timedelta(days=90))
    assert external.exists()
    assert not (tmp_path / "out/external").exists()
