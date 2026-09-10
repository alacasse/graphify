"""Owned Docker lifetimes and process termination through a controlled local CLI."""

import json
import multiprocessing
import os
import signal
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox.container_harness import ContainerHarness, ContainerRunResult

_FAKE_DOCKER = Path(__file__).with_name("fake_docker.py")
_IMAGE_ID = "sha256:" + "a" * 64


def arrange(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "subject").mkdir()
    (root / "subject/local.txt").write_text("uncommitted content")
    (root / "subject/.venv").mkdir()
    (root / "subject/.venv/excluded").touch()
    (root / "case.json").write_text("{}")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(root / "runtime"))


def conduct(root: Path, timeout: float = 2) -> tuple[ContainerRunResult, ContainerRunResult]:
    with ContainerHarness(
        runtime_executable=_FAKE_DOCKER,
        run_timeout_seconds=timeout,
        build_timeout_seconds=timeout,
        graceful_termination_seconds=0.1,
    ) as harness:
        try:
            result = harness.prepare(root / "subject", root / "preparation")
            if result.state == "completed":
                result = harness.run_case(
                    case_file=root / "case.json", output_directory=root / "output"
                )
        finally:
            cleanup = harness.cleanup()
    return result, cleanup


def commands(root: Path) -> list[list[str]]:
    return [json.loads(p.read_text()) for p in sorted((root / "runtime").glob("command-*"))]


def test_image_is_available_until_finalization_and_sources_are_captured_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange(tmp_path, monkeypatch)
    with ContainerHarness(runtime_executable=_FAKE_DOCKER) as harness:
        try:
            prepared = harness.prepare(tmp_path / "subject", tmp_path / "preparation")
            assert prepared.state == "completed" and prepared.image_id == _IMAGE_ID
            (tmp_path / "subject/local.txt").write_text("changed after build")
            first = harness.run_case(
                case_file=tmp_path / "case.json", output_directory=tmp_path / "one"
            )
            assert first.state == "completed" and first.cleanup_complete
            assert list((tmp_path / "runtime").glob("image-*"))
            assert not list((tmp_path / "runtime").glob("container-*"))
            second = harness.run_case(
                case_file=tmp_path / "case.json", output_directory=tmp_path / "two"
            )
            assert second.image_id == first.image_id
        finally:
            cleanup = harness.cleanup()
    assert cleanup.cleanup_complete
    assert (tmp_path / "runtime/reference/local.txt").read_text() == "uncommitted content"
    assert not (tmp_path / "runtime/reference/.venv").exists()
    calls = commands(tmp_path)
    runs = [c for c in calls if c[0] == "run"]
    assert len(runs) == 3 and "--help" in runs[0]
    for run in runs[1:]:
        mounts = [run[i + 1] for i, value in enumerate(run) if value == "--mount"]
        assert len(mounts) == 2 and sum("readonly" in m for m in mounts) == 1
        assert all("subject" not in m for m in mounts)
        assert run[run.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert not list((tmp_path / "runtime").glob("image-*"))
    build = next(c for c in calls if c[0] == "build")
    assert not Path(build[-1]).exists()
    assert (tmp_path / "one/journal.log").is_file() and (tmp_path / "two/journal.log").is_file()


def test_timeout_reaps_process_group_and_owned_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "run_timeout")
    result, cleanup = conduct(tmp_path, 0.3)
    assert result.state == "incomplete" and result.exit_code == 124
    assert result.cleanup_complete and cleanup.cleanup_complete
    child = int((tmp_path / "runtime/child-pid").read_text())
    assert _wait_until(lambda: not _process_is_live(child))
    assert not list((tmp_path / "runtime").glob("container-*"))


@pytest.mark.parametrize("sent_signal", [signal.SIGINT, signal.SIGTERM])
def test_signals_return_after_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sent_signal: signal.Signals,
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "hold")
    receiver, sender = multiprocessing.get_context("fork").Pipe(duplex=False)
    process = multiprocessing.get_context("fork").Process(
        target=_run_in_process, args=(tmp_path, sender)
    )
    process.start()
    sender.close()
    try:
        assert _wait_until(lambda: bool(list((tmp_path / "runtime").glob("ready-*"))))
        assert process.pid is not None
        os.kill(process.pid, sent_signal)
        assert receiver.poll(5)
        result, cleanup = cast(tuple[ContainerRunResult, ContainerRunResult], receiver.recv())
        process.join(timeout=5)
        assert process.exitcode == 0 and result.state == "interrupted"
        assert result.exit_code == 128 + sent_signal
        assert cleanup.cleanup_complete
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        receiver.close()


def _run_in_process(root: Path, sender: Connection) -> None:
    sender.send(conduct(root, 10))
    sender.close()


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf")])
def test_invalid_budgets_never_start_runtime(budget: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        ContainerHarness(run_timeout_seconds=budget)


def test_full_build_logs_survive_bounded_diagnostic_tails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_VERBOSE", "1")
    result, cleanup = conduct(tmp_path)
    assert cleanup.cleanup_complete and len(result.stdout_tail) <= 64 * 1024
    assert "A" * 70_000 in (tmp_path / "preparation/build.log").read_text()


def _wait_until(check: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


def _process_is_live(process_id: int) -> bool:
    status = Path(f"/proc/{process_id}/stat")
    if not status.exists():
        return False
    fields = status.read_text(encoding="utf-8").split()
    return len(fields) > 2 and fields[2] != "Z"
