"""Build and run the isolated install-sandbox Docker probe."""

from __future__ import annotations

import json
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
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Literal, TextIO

__all__ = ["ContainerHarness", "ContainerProbeRequest", "ContainerProbeResult"]

_ATTESTATION_NAME = "infrastructure-probe.json"
_CONTAINER_ROOTS = {
    "home": "/sandbox/home",
    "output": "/sandbox/output",
    "prepared_source": "/sandbox/source",
    "project": "/sandbox/project",
    "subject": "/sandbox/subject",
    "working_directory": "/sandbox/work",
    "xdg": "/sandbox/xdg",
}
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TAIL_LIMIT = 64 * 1024

ProbeState = Literal["passed", "incomplete", "interrupted"]
ProbePhase = Literal["preflight", "build", "run", "cleanup", "complete"]


@dataclass(frozen=True, slots=True)
class ContainerProbeRequest:
    """Inputs and operational budgets for one isolated probe invocation."""

    subject_checkout: Path
    output_directory: Path
    runtime_executable: str | Path = "docker"
    build_timeout_seconds: float = 60.0
    run_timeout_seconds: float = 120.0
    graceful_termination_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class ContainerProbeResult:
    """Closed infrastructure result returned by :meth:`ContainerHarness.run_probe`."""

    run_id: str
    state: ProbeState
    phase: ProbePhase
    exit_code: int
    image_id: str | None
    attestation_path: Path | None
    cleanup_complete: bool
    stdout_tail: str
    stderr_tail: str
    detail: str


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    subject_checkout: Path
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
    state: ProbeState
    phase: ProbePhase
    exit_code: int
    detail: str
    attestation_path: Path | None = None


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

    def add(self, phase: ProbePhase, result: _CommandResult) -> None:
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
    """Own the complete Docker probe build, run, validation, and cleanup lifecycle."""

    def run_probe(self, request: ContainerProbeRequest) -> ContainerProbeResult:
        """Run one probe and return a fail-closed infrastructure result."""

        run_id = uuid.uuid4().hex
        try:
            prepared = _prepare_request(request)
        except _PreflightError as exc:
            return _preflight_failure(run_id, str(exc))
        return _ProbeRun(prepared, run_id).execute()


class _ProbeRun:
    def __init__(self, request: _PreparedRequest, run_id: str) -> None:
        self.request = request
        self.run_id = run_id
        self.image_tag = f"install-sandbox-probe:{run_id}"
        self.container_name = f"install-sandbox-probe-{run_id}"
        self.image_id: str | None = None
        self.build_attempted = False
        self.run_attempted = False
        self.diagnostics = _DiagnosticTails()
        self.interrupts = _SignalCapture()

    def execute(self) -> ContainerProbeResult:
        with self.interrupts:
            daemon_outcome = self._check_daemon()
            if daemon_outcome is not None:
                return self._result(daemon_outcome, cleanup_complete=True)
            try:
                outcome = self._build_and_run()
            except Exception as exc:
                outcome = _Outcome("incomplete", "run", 2, f"unexpected harness error: {exc}")
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
            build_outcome = self._build_image(image_id_file)
            if build_outcome is not None:
                return build_outcome
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
        failure = _command_failure(result, "build", "probe image build failed")
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
        failure = _command_failure(result, "run", "probe container failed")
        if failure is not None:
            return failure
        return self._validate_attestation()

    def _run_command(self, image_id: str) -> list[str]:
        uid = os.getuid()
        gid = os.getgid()
        subject_mount = _mount(self.request.subject_checkout, _CONTAINER_ROOTS["subject"], True)
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
            output_mount,
            "--env",
            f"INSTALL_SANDBOX_RUN_ID={self.run_id}",
            "--env",
            f"INSTALL_SANDBOX_IMAGE_ID={image_id}",
            "--workdir",
            _CONTAINER_ROOTS["working_directory"],
            image_id,
        ]

    def _validate_attestation(self) -> _Outcome:
        path = self.request.output_directory / _ATTESTATION_NAME
        try:
            document = _read_attestation(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            existing = path if path.exists() else None
            return _Outcome("incomplete", "run", 2, f"invalid probe attestation: {exc}", existing)
        expected = _expected_attestation(self.run_id, self.image_id)
        if document != expected:
            return _Outcome("incomplete", "run", 2, "probe attestation is incoherent", path)
        return _Outcome("passed", "complete", 0, "probe passed", path)

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
        phase: ProbePhase,
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

    def _result(self, outcome: _Outcome, cleanup_complete: bool) -> ContainerProbeResult:
        return ContainerProbeResult(
            run_id=self.run_id,
            state=outcome.state,
            phase=outcome.phase,
            exit_code=outcome.exit_code,
            image_id=self.image_id,
            attestation_path=outcome.attestation_path,
            cleanup_complete=cleanup_complete,
            stdout_tail=self.diagnostics.stdout.value,
            stderr_tail=self.diagnostics.stderr.value,
            detail=outcome.detail,
        )


def _prepare_request(request: ContainerProbeRequest) -> _PreparedRequest:
    if threading.current_thread() is not threading.main_thread():
        raise _PreflightError("run_probe must be called from the process main thread")
    if os.name != "posix" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise _PreflightError("this slice requires a POSIX host with UID/GID support")
    _validate_budgets(request)
    runtime = str(request.runtime_executable)
    if not runtime:
        raise _PreflightError("runtime_executable must not be empty")
    subject = _resolve_subject(request.subject_checkout)
    output = _prepare_output(request.output_directory)
    if _paths_overlap(subject, output):
        raise _PreflightError("output_directory must not overlap subject_checkout")
    if "," in str(subject) or "," in str(output):
        raise _PreflightError("Docker mount paths containing commas are unsupported")
    return _PreparedRequest(
        subject,
        output,
        runtime,
        request.build_timeout_seconds,
        request.run_timeout_seconds,
        request.graceful_termination_seconds,
    )


def _validate_budgets(request: ContainerProbeRequest) -> None:
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


def _preflight_failure(run_id: str, detail: str) -> ContainerProbeResult:
    return ContainerProbeResult(
        run_id=run_id,
        state="incomplete",
        phase="preflight",
        exit_code=2,
        image_id=None,
        attestation_path=None,
        cleanup_complete=True,
        stdout_tail="",
        stderr_tail="",
        detail=detail,
    )


def _command_failure(
    result: _CommandResult,
    phase: ProbePhase,
    detail: str,
) -> _Outcome | None:
    if result.interrupted_by is not None:
        return _interrupted(phase, result.interrupted_by)
    if result.timed_out:
        return _Outcome("incomplete", phase, 124, f"{detail}: timed out")
    if result.exit_code != 0:
        return _Outcome("incomplete", phase, result.exit_code or 2, detail)
    return None


def _interrupted(phase: ProbePhase, signal_number: int) -> _Outcome:
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
        outcome.attestation_path,
    )


def _expected_attestation(run_id: str, image_id: str | None) -> dict[str, object]:
    return {
        "checks": {
            "output_write_succeeded": True,
            "roots_distinct": True,
            "subject_mount_read_only": True,
            "subject_write_rejected": True,
        },
        "identity": {"gid": os.getgid(), "uid": os.getuid()},
        "image_id": image_id,
        "image_payload": ["probe.py"],
        "paths": _CONTAINER_ROOTS,
        "run_id": run_id,
        "schema_version": 1,
    }


def _read_attestation(path: Path) -> object:
    if path.stat().st_size > _TAIL_LIMIT:
        raise ValueError("attestation exceeds 64 KiB")
    return json.loads(path.read_text(encoding="utf-8"))


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
