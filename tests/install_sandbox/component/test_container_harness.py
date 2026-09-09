from __future__ import annotations

import json
import multiprocessing
import os
import signal
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import TypedDict, cast

import pytest

from tools.install_sandbox.container_harness import (
    ContainerHarness,
    ContainerRunResult,
)

_FAKE_DOCKER = Path(__file__).with_name("fake_docker.py")
_IMAGE_ID = "sha256:" + ("a" * 64)


def test_success_uses_immutable_image_and_owned_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_VERBOSE", "1")

    result = ContainerHarness().run_case(**_request(subject, output))

    assert result.state == "completed"
    assert result.phase == "complete"
    assert result.exit_code == 0
    assert result.image_id == _IMAGE_ID
    assert result.cleanup_complete
    assert len(result.stdout_tail) <= 64 * 1024
    commands = _commands(state)
    build = _command(commands, "build")
    run = _command(commands, "run")
    image_remove = _command(commands, "image", "rm")
    tag = build[build.index("--tag") + 1]
    assert _IMAGE_ID in run
    assert run[run.index(_IMAGE_ID) + 1 :] == [
        "--subject-checkout",
        "/sandbox/subject",
        "--case-file",
        "/sandbox/case.json",
        "--output-directory",
        "/sandbox/output",
        "--work-directory",
        "/sandbox/work/case",
    ]
    assert tag not in run
    assert image_remove[-1] == tag
    assert _IMAGE_ID not in image_remove
    _assert_mounts(run, subject, output)
    assert "--network" not in run
    assert not list(state.glob("image-*"))
    assert not list(state.glob("container-*"))
    assert (output / "journal.log").read_text() == "controlled container evidence\n"
    (output / "journal.log").write_text("caller-owned")
    assert (output / "journal.log").read_text() == "caller-owned"


@pytest.mark.parametrize(
    ("mode", "state_name", "phase", "exit_code", "cleanup"),
    [
        ("daemon_fail", "incomplete", "preflight", 3, True),
        ("build_fail", "incomplete", "build", 7, True),
        ("run_fail", "incomplete", "run", 9, True),
        ("missing_image_id", "incomplete", "build", 2, True),
        ("invalid_image_id", "incomplete", "build", 2, True),
        ("cleanup_fail", "incomplete", "cleanup", 2, False),
        ("container_cleanup_fail", "incomplete", "cleanup", 2, False),
    ],
)
def test_failures_are_classified_and_cleanup_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    state_name: str,
    phase: str,
    exit_code: int,
    cleanup: bool,
) -> None:
    subject, output, _state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)

    result = ContainerHarness().run_case(**_request(subject, output))

    assert result.state == state_name
    assert result.phase == phase
    assert result.exit_code == exit_code
    assert result.cleanup_complete is cleanup


def test_timeout_reaps_the_runtime_process_group_and_owned_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "run_timeout")
    request = _request(subject, output, run_timeout=0.2, grace=0.1)

    result = ContainerHarness().run_case(**request)

    assert result.state == "incomplete"
    assert result.phase == "run"
    assert result.exit_code == 124
    assert result.cleanup_complete
    child_pid = int((state / "child-pid").read_text(encoding="utf-8"))
    assert _wait_until(lambda: not _process_is_live(child_pid))
    assert not list(state.glob("container-*"))
    assert not list(state.glob("image-*"))


def test_build_and_run_have_separate_timeout_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "build_timeout")
    request = _request(subject, output, build_timeout=0.1, run_timeout=2.0, grace=0.1)

    result = ContainerHarness().run_case(**request)

    assert result.state == "incomplete"
    assert result.phase == "build"
    assert result.exit_code == 124
    assert result.cleanup_complete
    assert not any(command[0] == "run" for command in _commands(state))


@pytest.mark.parametrize(
    ("sent_signal", "exit_code"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_signals_return_after_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sent_signal: signal.Signals,
    exit_code: int,
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "hold")
    request = _request(subject, output, grace=0.1)
    receiver, sender = multiprocessing.get_context("fork").Pipe(duplex=False)
    process = multiprocessing.get_context("fork").Process(
        target=_run_in_process,
        args=(request, sender),
    )
    process.start()
    sender.close()
    assert _wait_until(lambda: bool(list(state.glob("ready-*"))))
    assert process.pid is not None
    os.kill(process.pid, sent_signal)
    result = cast(ContainerRunResult, receiver.recv())
    process.join(timeout=5)

    assert process.exitcode == 0
    assert result.state == "interrupted"
    assert result.exit_code == exit_code
    assert result.cleanup_complete
    assert not list(state.glob("container-*"))
    assert not list(state.glob("image-*"))


def test_nonempty_or_overlapping_output_fails_before_the_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, _output, state = _arrange(tmp_path, monkeypatch)
    output = subject / "output"
    output.mkdir()

    result = ContainerHarness().run_case(**_request(subject, output))

    assert result.state == "incomplete"
    assert result.phase == "preflight"
    assert result.exit_code == 2
    assert "overlap" in result.detail
    assert not list(state.glob("command-*"))


def test_nonempty_output_fails_before_the_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    output.mkdir()
    (output / "existing.txt").write_text("keep", encoding="utf-8")

    result = ContainerHarness().run_case(**_request(subject, output))

    assert result.state == "incomplete"
    assert result.phase == "preflight"
    assert "empty" in result.detail
    assert (output / "existing.txt").read_text(encoding="utf-8") == "keep"
    assert not list(state.glob("command-*"))


def _arrange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "README.md").write_text("subject", encoding="utf-8")
    output = tmp_path / "output"
    (tmp_path / "case.json").write_text("{}", encoding="utf-8")
    state = tmp_path / "fake-state"
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state))
    monkeypatch.delenv("FAKE_DOCKER_MODE", raising=False)
    monkeypatch.delenv("FAKE_DOCKER_VERBOSE", raising=False)
    return subject, output, state


class _RunArguments(TypedDict):
    subject_checkout: Path
    case_file: Path
    output_directory: Path
    runtime_executable: Path
    build_timeout_seconds: float
    run_timeout_seconds: float
    graceful_termination_seconds: float


def _request(
    subject: Path,
    output: Path,
    *,
    build_timeout: float = 2.0,
    run_timeout: float = 2.0,
    grace: float = 0.2,
) -> _RunArguments:
    return _RunArguments(
        subject_checkout=subject,
        case_file=subject.parent / "case.json",
        output_directory=output,
        runtime_executable=_FAKE_DOCKER,
        build_timeout_seconds=build_timeout,
        run_timeout_seconds=run_timeout,
        graceful_termination_seconds=grace,
    )


def _run_in_process(request: _RunArguments, sender: Connection) -> None:
    sender.send(ContainerHarness().run_case(**request))
    sender.close()


def _commands(state: Path) -> list[list[str]]:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in state.glob("command-*")]
    return [cast(list[str], document) for document in documents]


def _command(commands: list[list[str]], *prefix: str) -> list[str]:
    return next(command for command in commands if command[: len(prefix)] == list(prefix))


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def _assert_mounts(command: list[str], subject: Path, output: Path) -> None:
    mounts = [command[index + 1] for index, item in enumerate(command) if item == "--mount"]
    assert mounts == [
        f"type=bind,src={subject.resolve()},dst=/sandbox/subject,readonly",
        f"type=bind,src={subject.parent / 'case.json'},dst=/sandbox/case.json,readonly",
        f"type=bind,src={output.resolve()},dst=/sandbox/output",
    ]
    sources = [
        next(part.removeprefix("src=") for part in mount.split(",") if part.startswith("src="))
        for mount in mounts
    ]
    assert str(Path.home().resolve()) not in sources


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


@pytest.mark.parametrize("mode", ["success", "invalid_result"])
def test_container_completion_does_not_validate_case_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    subject, output, _state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    result = ContainerHarness().run_case(**_request(subject, output))
    assert result.state == "completed"
    assert result.cleanup_complete
    if mode == "success":
        assert not (output / "result.json").exists()
    else:
        assert (output / "result.json").read_text() == "{"


@pytest.mark.parametrize("mode", ["run_fail", "run_timeout", "cleanup_fail"])
def test_partial_evidence_and_diagnostics_survive_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    subject, output, _state = _arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    result = ContainerHarness().run_case(**_request(subject, output, run_timeout=0.3, grace=0.1))
    assert result.state == "incomplete"
    assert "container started" in result.stdout_tail
    assert (output / "journal.log").read_text() == "controlled container evidence\n"
    assert (subject / "README.md").read_text() == "subject"
    assert (tmp_path / "case.json").read_text() == "{}"
    if mode == "run_fail":
        assert "run failed" in result.stderr_tail


def test_foreign_resources_remain_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    state.mkdir()
    foreign = [state / "image-foreign", state / "container-foreign"]
    for path in foreign:
        path.write_text("foreign resource")
    result = ContainerHarness().run_case(**_request(subject, output))
    assert result.state == "completed"
    assert all(path.read_text() == "foreign resource" for path in foreign)
    commands = _commands(state)
    assert not any("prune" in command for command in commands)
    removals = [command for command in commands if command[:2] == ["image", "rm"]]
    assert [command[-1] for command in removals] == [f"install-sandbox-case:{result.run_id}"]


@pytest.mark.parametrize("kind", ["missing", "directory", "inside_output", "comma"])
def test_invalid_case_path_is_rejected_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    case = tmp_path / "case.json"
    if kind == "missing":
        case.unlink()
    elif kind == "directory":
        case.unlink()
        case.mkdir()
    elif kind == "inside_output":
        output.mkdir()
        case = case.rename(output / "case.json")
    else:
        case = case.rename(tmp_path / "case,comma.json")
    arguments = _request(subject, output)
    arguments["case_file"] = case
    result = ContainerHarness().run_case(**arguments)
    assert result.phase == "preflight"
    assert result.state == "incomplete"
    assert not list(state.glob("command-*"))
    assert "case_file" in result.detail or "commas" in result.detail


def test_overlapping_new_output_does_not_modify_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, _output, state = _arrange(tmp_path, monkeypatch)
    output = subject / "new" / "output"
    result = ContainerHarness().run_case(**_request(subject, output))
    assert result.phase == "preflight"
    assert not (subject / "new").exists()
    assert not list(state.glob("command-*"))


@pytest.mark.parametrize("budget", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_budget_never_starts_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: float
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    result = ContainerHarness().run_case(**_request(subject, output, run_timeout=budget))
    assert result.phase == "preflight"
    assert "finite and positive" in result.detail
    assert not list(state.glob("command-*"))


def test_build_context_and_mounts_do_not_depend_on_developer_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, output, state = _arrange(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = ContainerHarness().run_case(**_request(subject, output))
    assert result.state == "completed"
    build = _command(_commands(state), "build")
    context = Path(__file__).resolve().parents[3] / "tools/install_sandbox"
    assert Path(build[-1]) == context
    assert Path(_option(build, "--file")) == context / "Containerfile"
    run = _command(_commands(state), "run")
    assert _option(run, "--user") == f"{os.getuid()}:{os.getgid()}"
    assert _option(run, "--workdir") == "/sandbox/work"
    _assert_mounts(run, subject, output)
