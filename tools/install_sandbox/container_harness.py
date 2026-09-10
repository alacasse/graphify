"""Build and run one installation case in an isolated Docker container."""

from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import FrameType
from typing import Literal, TextIO

from tools.install_sandbox.timings import Timing, elapsed, measure, skip_pending

__all__ = ["ContainerHarness", "ContainerRunResult"]

_CONTAINER_ROOTS = {
    "subject": "/sandbox/subject",
    "case": "/sandbox/case.json",
    "output": "/sandbox/output",
    "working_directory": "/sandbox/work",
}
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TAIL_LIMIT = 64 * 1024

RunState = Literal["completed", "incomplete", "interrupted"]
RunPhase = Literal["preflight", "build", "run", "cleanup", "complete"]


@dataclass(frozen=True, slots=True)
class ContainerRunResult:
    """Closed infrastructure result returned by :meth:`ContainerHarness.run_case`."""

    run_id: str
    state: RunState
    phase: RunPhase
    exit_code: int
    image_id: str | None
    cleanup_complete: bool
    stdout_tail: str
    stderr_tail: str
    detail: str
    timings: list[Timing] = field(default_factory=list[Timing])


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    subject_checkout: Path
    case_file: Path
    output_directory: Path
    runtime_executable: str
    build_timeout_seconds: float
    run_timeout_seconds: float
    graceful_termination_seconds: float


@dataclass(frozen=True, slots=True)
class _CommandResult:
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    interrupted_by: int | None = None


@dataclass(frozen=True, slots=True)
class _Outcome:
    state: RunState
    phase: RunPhase
    exit_code: int
    detail: str


class _PreflightError(ValueError):
    pass


class _Tail:
    def __init__(self, limit: int = _TAIL_LIMIT) -> None:
        self._limit = limit
        self._value = ""

    def append(self, value: str) -> None:
        self._value = (self._value + value)[-self._limit :]

    @property
    def value(self) -> str:
        return self._value


class _DiagnosticTails:
    def __init__(self) -> None:
        self.stdout = _Tail()
        self.stderr = _Tail()

    def add(self, phase: RunPhase, result: _CommandResult) -> None:
        if result.stdout_tail:
            self.stdout.append(f"[{phase}]\n{result.stdout_tail}")
        if result.stderr_tail:
            self.stderr.append(f"[{phase}]\n{result.stderr_tail}")


class _SignalCapture:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.signal_number: int | None = None
        self._previous: dict[
            signal.Signals,
            int | Callable[[int, FrameType | None], None] | None,
        ] = {}

    def __enter__(self) -> _SignalCapture:
        for caught_signal in (signal.SIGINT, signal.SIGTERM):
            self._previous[caught_signal] = signal.signal(caught_signal, self._handle)
        return self

    def __exit__(self, *_args: object) -> None:
        for caught_signal, previous in self._previous.items():
            signal.signal(caught_signal, previous)

    def _handle(self, signal_number: int, _frame: FrameType | None) -> None:
        if self.signal_number is None:
            self.signal_number = signal_number
        self.event.set()


class ContainerHarness:
    """Own image construction, case container execution, and invocation cleanup."""

    def run_case(
        self,
        *,
        subject_checkout: Path,
        case_file: Path,
        output_directory: Path,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300.0,
        run_timeout_seconds: float = 900.0,
        graceful_termination_seconds: float = 10.0,
    ) -> ContainerRunResult:
        """Run one container; case conformity is reported separately by the runner."""
        started = time.monotonic_ns()
        timings = [Timing(phase) for phase in ("preflight", "build", "run", "cleanup")]
        run_id = uuid.uuid4().hex
        request = _PreparedRequest(
            subject_checkout,
            case_file,
            output_directory,
            str(runtime_executable),
            build_timeout_seconds,
            run_timeout_seconds,
            graceful_termination_seconds,
        )
        try:
            prepared = _prepare_request(request)
        except (_PreflightError, OSError, RuntimeError) as exc:
            timings[0] = Timing("preflight", state="measured", duration_seconds=elapsed(started))
            skip_pending(timings)
            return replace(_preflight_failure(run_id, str(exc)), timings=timings)
        return _ContainerRun(prepared, run_id, timings, started).execute()


class _ContainerRun:
    def __init__(
        self, request: _PreparedRequest, run_id: str, timings: list[Timing], started: int
    ) -> None:
        self.timings = timings
        self.started = started
        self.request = request
        self.run_id = run_id
        self.image_tag = f"install-sandbox-case:{run_id}"
        self.container_name = f"install-sandbox-case-{run_id}"
        self.image_id: str | None = None
        self.build_attempted = False
        self.run_attempted = False
        self.diagnostics = _DiagnosticTails()
        self.interrupts = _SignalCapture()

    def execute(self) -> ContainerRunResult:
        with self.interrupts:
            daemon_outcome = self._check_daemon()
            self.timings[0] = Timing(
                "preflight", state="measured", duration_seconds=elapsed(self.started)
            )
            if daemon_outcome is not None:
                return self._result(daemon_outcome, cleanup_complete=True)
            try:
                outcome = self._build_and_run()
            except Exception as exc:
                outcome = _Outcome("incomplete", "run", 2, f"unexpected harness error: {exc}")
            with measure(self.timings[3]):
                outcome, cleanup_complete = self._cleanup_outcome(outcome)
            if cleanup_complete and self.interrupts.signal_number is not None:
                outcome = _interrupted("cleanup", self.interrupts.signal_number)
        return self._result(_apply_cleanup(outcome, cleanup_complete), cleanup_complete)

    def _cleanup_outcome(self, outcome: _Outcome) -> tuple[_Outcome, bool]:
        try:
            return outcome, self._cleanup()
        except Exception as exc:
            detail = f"{outcome.detail}; cleanup raised: {exc}"
            return _Outcome("incomplete", "cleanup", outcome.exit_code or 2, detail), False

    def _check_daemon(self) -> _Outcome | None:
        command = [
            self.request.runtime_executable,
            "version",
            "--format",
            "{{.Server.Version}}",
        ]
        result = self._command(command, min(self.request.build_timeout_seconds, 10.0), "preflight")
        return _command_failure(result, "preflight", "Docker daemon preflight failed")

    def _build_and_run(self) -> _Outcome:
        if self.interrupts.signal_number is not None:
            return _interrupted("build", self.interrupts.signal_number)
        with tempfile.TemporaryDirectory(prefix=f"install-sandbox-{self.run_id}-") as temporary:
            image_id_file = Path(temporary) / "image-id"
            with measure(self.timings[1]):
                build_outcome = self._build_image(image_id_file)
            if build_outcome is not None:
                return build_outcome
            if self.interrupts.signal_number is not None:
                return _interrupted("run", self.interrupts.signal_number)
            with measure(self.timings[2]):
                return self._run_image()

    def _build_image(self, image_id_file: Path) -> _Outcome | None:
        context = Path(__file__).resolve().parent
        self.build_attempted = True
        command = [
            self.request.runtime_executable,
            "build",
            "--file",
            str(context / "Containerfile"),
            "--tag",
            self.image_tag,
            "--iidfile",
            str(image_id_file),
            str(context),
        ]
        result = self._command(command, self.request.build_timeout_seconds, "build")
        failure = _command_failure(result, "build", "case image build failed")
        if failure is not None:
            return failure
        return self._load_image_id(image_id_file)

    def _load_image_id(self, image_id_file: Path) -> _Outcome | None:
        try:
            image_id = image_id_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return _Outcome("incomplete", "build", 2, f"image ID was not produced: {exc}")
        if _IMAGE_ID.fullmatch(image_id) is None:
            return _Outcome("incomplete", "build", 2, "image ID is missing or malformed")
        self.image_id = image_id
        return None

    def _run_image(self) -> _Outcome:
        if self.interrupts.signal_number is not None:
            return _interrupted("run", self.interrupts.signal_number)
        assert self.image_id is not None
        self.run_attempted = True
        result = self._command(
            self._run_command(self.image_id),
            self.request.run_timeout_seconds,
            "run",
        )
        failure = _command_failure(result, "run", "case container failed")
        if failure is not None:
            return failure
        return _Outcome("completed", "complete", 0, "case container completed")

    def _run_command(self, image_id: str) -> list[str]:
        uid = os.getuid()
        gid = os.getgid()
        subject_mount = _mount(self.request.subject_checkout, _CONTAINER_ROOTS["subject"], True)
        case_mount = _mount(self.request.case_file, _CONTAINER_ROOTS["case"], True)
        output_mount = _mount(self.request.output_directory, _CONTAINER_ROOTS["output"], False)
        return [
            self.request.runtime_executable,
            "run",
            "--rm",
            "--name",
            self.container_name,
            "--user",
            f"{uid}:{gid}",
            "--mount",
            subject_mount,
            "--mount",
            case_mount,
            "--mount",
            output_mount,
            "--env",
            f"INSTALL_SANDBOX_RUN_ID={self.run_id}",
            "--env",
            f"INSTALL_SANDBOX_IMAGE_ID={image_id}",
            "--workdir",
            _CONTAINER_ROOTS["working_directory"],
            image_id,
            "--subject-checkout",
            _CONTAINER_ROOTS["subject"],
            "--case-file",
            _CONTAINER_ROOTS["case"],
            "--output-directory",
            _CONTAINER_ROOTS["output"],
            "--work-directory",
            _CONTAINER_ROOTS["working_directory"] + "/case",
        ]

    def _cleanup(self) -> bool:
        if not self.build_attempted:
            return True
        container_absent = self._cleanup_container()
        image_tag_absent = self._cleanup_image_tag()
        return container_absent and image_tag_absent

    def _cleanup_container(self) -> bool:
        if not self.run_attempted or self._container_absent():
            return True
        timeout = max(15.0, self.request.graceful_termination_seconds + 5.0)
        grace = str(max(1, math.ceil(self.request.graceful_termination_seconds)))
        self._cleanup_command(["stop", "--time", grace, self.container_name], timeout)
        if not self._container_absent():
            self._cleanup_command(["kill", self.container_name], timeout)
        if not self._container_absent():
            self._cleanup_command(["rm", "--force", self.container_name], timeout)
        return self._container_absent()

    def _container_absent(self) -> bool:
        result = self._cleanup_command(
            ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{self.container_name}$"],
            15.0,
        )
        return result.exit_code == 0 and not result.stdout_tail.strip()

    def _cleanup_image_tag(self) -> bool:
        if self._image_tag_absent():
            return True
        self._cleanup_command(["image", "rm", "--force", self.image_tag], 15.0)
        return self._image_tag_absent()

    def _image_tag_absent(self) -> bool:
        result = self._cleanup_command(
            ["image", "ls", "--quiet", "--filter", f"reference={self.image_tag}"],
            15.0,
        )
        return result.exit_code == 0 and not result.stdout_tail.strip()

    def _cleanup_command(self, arguments: list[str], timeout: float) -> _CommandResult:
        return self._command(
            [self.request.runtime_executable, *arguments],
            timeout,
            "cleanup",
            observe_interrupts=False,
        )

    def _command(
        self,
        command: Sequence[str],
        timeout: float,
        phase: RunPhase,
        *,
        observe_interrupts: bool = True,
    ) -> _CommandResult:
        interrupts = self.interrupts if observe_interrupts else None
        result = _execute_command(
            command,
            timeout,
            self.request.graceful_termination_seconds,
            interrupts,
        )
        self.diagnostics.add(phase, result)
        return result

    def _result(self, outcome: _Outcome, cleanup_complete: bool) -> ContainerRunResult:
        skip_pending(self.timings)
        return ContainerRunResult(
            run_id=self.run_id,
            state=outcome.state,
            phase=outcome.phase,
            exit_code=outcome.exit_code,
            image_id=self.image_id,
            cleanup_complete=cleanup_complete,
            stdout_tail=self.diagnostics.stdout.value,
            stderr_tail=self.diagnostics.stderr.value,
            detail=outcome.detail,
            timings=self.timings,
        )


def _prepare_request(request: _PreparedRequest) -> _PreparedRequest:
    if threading.current_thread() is not threading.main_thread():
        raise _PreflightError("run_case must be called from the process main thread")
    if os.name != "posix" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise _PreflightError("this slice requires a POSIX host with UID/GID support")
    _validate_budgets(request)
    runtime = str(request.runtime_executable)
    if not runtime:
        raise _PreflightError("runtime_executable must not be empty")
    subject = _resolve_subject(request.subject_checkout)
    case_file = _resolve_case(request.case_file)
    output = request.output_directory.expanduser().resolve()
    _validate_mount_paths(subject, case_file, output)
    output = _prepare_output(request.output_directory)
    if "/" in runtime:
        runtime = str(Path(runtime).expanduser().resolve())
    return _PreparedRequest(
        subject,
        case_file,
        output,
        runtime,
        request.build_timeout_seconds,
        request.run_timeout_seconds,
        request.graceful_termination_seconds,
    )


def _resolve_case(case_file: Path) -> Path:
    try:
        resolved = case_file.expanduser().resolve(strict=True)
    except OSError as exc:
        raise _PreflightError(f"case_file is unavailable: {exc}") from exc
    if not resolved.is_file():
        raise _PreflightError("case_file must be a regular file")
    return resolved


def _validate_mount_paths(subject: Path, case_file: Path, output: Path) -> None:
    if _paths_overlap(subject, output):
        raise _PreflightError("output_directory must not overlap subject_checkout")
    if _paths_overlap(case_file, output):
        raise _PreflightError("case_file must be outside output_directory")
    if any("," in str(path) for path in (subject, case_file, output)):
        raise _PreflightError("Docker mount paths containing commas are unsupported")


def _validate_budgets(request: _PreparedRequest) -> None:
    budgets = {
        "build_timeout_seconds": request.build_timeout_seconds,
        "run_timeout_seconds": request.run_timeout_seconds,
        "graceful_termination_seconds": request.graceful_termination_seconds,
    }
    invalid = [name for name, value in budgets.items() if not math.isfinite(value) or value <= 0]
    if invalid:
        names = ", ".join(invalid)
        raise _PreflightError(f"operational budgets must be finite and positive: {names}")


def _resolve_subject(subject: Path) -> Path:
    try:
        resolved = subject.expanduser().resolve(strict=True)
    except OSError as exc:
        raise _PreflightError(f"subject_checkout is unavailable: {exc}") from exc
    if not resolved.is_dir():
        raise _PreflightError("subject_checkout must be a directory")
    return resolved


def _prepare_output(output: Path) -> Path:
    expanded = output.expanduser()
    if expanded.is_symlink():
        raise _PreflightError("output_directory must not be a symlink")
    try:
        expanded.mkdir(parents=True, exist_ok=True)
        resolved = expanded.resolve(strict=True)
        if not resolved.is_dir():
            raise _PreflightError("output_directory must be a directory")
        if any(resolved.iterdir()):
            raise _PreflightError("output_directory must be empty")
    except _PreflightError:
        raise
    except OSError as exc:
        raise _PreflightError(f"output_directory is unavailable: {exc}") from exc
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _mount(source: Path, destination: str, read_only: bool) -> str:
    options = f"type=bind,src={source},dst={destination}"
    return f"{options},readonly" if read_only else options


def _preflight_failure(run_id: str, detail: str) -> ContainerRunResult:
    return ContainerRunResult(
        run_id=run_id,
        state="incomplete",
        phase="preflight",
        exit_code=2,
        image_id=None,
        cleanup_complete=True,
        stdout_tail="",
        stderr_tail="",
        detail=detail,
    )


def _command_failure(
    result: _CommandResult,
    phase: RunPhase,
    detail: str,
) -> _Outcome | None:
    if result.interrupted_by is not None:
        return _interrupted(phase, result.interrupted_by)
    if result.timed_out:
        return _Outcome("incomplete", phase, 124, f"{detail}: timed out")
    if result.exit_code != 0:
        return _Outcome("incomplete", phase, result.exit_code or 2, detail)
    return None


def _interrupted(phase: RunPhase, signal_number: int) -> _Outcome:
    return _Outcome(
        "interrupted",
        phase,
        128 + signal_number,
        f"interrupted by signal {signal_number}",
    )


def _apply_cleanup(outcome: _Outcome, cleanup_complete: bool) -> _Outcome:
    if cleanup_complete:
        return outcome
    exit_code = outcome.exit_code if outcome.exit_code != 0 else 2
    return _Outcome(
        "incomplete",
        "cleanup",
        exit_code,
        f"{outcome.detail}; owned Docker resources remain",
    )


def _execute_command(
    command: Sequence[str],
    timeout_seconds: float,
    graceful_termination_seconds: float,
    interrupts: _SignalCapture | None,
) -> _CommandResult:
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return _CommandResult(127, stderr_tail=str(exc))
    except OSError as exc:
        return _CommandResult(2, stderr_tail=str(exc))
    return _observe_process(process, timeout_seconds, graceful_termination_seconds, interrupts)


def _observe_process(
    process: subprocess.Popen[str],
    timeout_seconds: float,
    graceful_termination_seconds: float,
    interrupts: _SignalCapture | None,
) -> _CommandResult:
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_tail = _Tail()
    stderr_tail = _Tail()
    readers = [
        threading.Thread(target=_pump_stream, args=(process.stdout, sys.stdout, stdout_tail)),
        threading.Thread(target=_pump_stream, args=(process.stderr, sys.stderr, stderr_tail)),
    ]
    for reader in readers:
        reader.start()
    timed_out, interrupted_by = _wait_for_process(process, timeout_seconds, interrupts)
    if timed_out or interrupted_by is not None:
        _terminate_process_group(process, graceful_termination_seconds)
    else:
        process.wait()
    for reader in readers:
        reader.join(timeout=2.0)
    return _CommandResult(
        process.returncode if process.returncode is not None else 2,
        stdout_tail.value,
        stderr_tail.value,
        timed_out,
        interrupted_by,
    )


def _wait_for_process(
    process: subprocess.Popen[str],
    timeout_seconds: float,
    interrupts: _SignalCapture | None,
) -> tuple[bool, int | None]:
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        if interrupts is not None and interrupts.event.wait(timeout=0.05):
            return False, interrupts.signal_number
        if time.monotonic() >= deadline:
            return True, None
    return False, None


def _terminate_process_group(
    process: subprocess.Popen[str],
    graceful_termination_seconds: float,
) -> None:
    deadline = time.monotonic() + graceful_termination_seconds
    _signal_process_group(process, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=graceful_termination_seconds)
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    _signal_process_group(process, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=max(1.0, graceful_termination_seconds))


def _signal_process_group(process: subprocess.Popen[str], sent_signal: signal.Signals) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, sent_signal)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _pump_stream(source: TextIO, destination: TextIO, tail: _Tail) -> None:
    for line in iter(source.readline, ""):
        tail.append(line)
        try:
            destination.write(line)
            destination.flush()
        except (BrokenPipeError, OSError):
            pass
