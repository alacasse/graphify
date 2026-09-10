"""Prepare one image, run fresh case containers, and clean only owned resources."""

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
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Literal, TextIO

from tools.install_sandbox.preparer import prepare_context
from tools.install_sandbox.timings import Timing, measure, skip_pending

__all__ = ["ContainerHarness", "ContainerRunResult"]

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TAIL_LIMIT = 64 * 1024

RunState = Literal["completed", "incomplete", "interrupted"]
RunPhase = Literal["preflight", "build", "verify", "run", "cleanup", "complete"]


@dataclass(frozen=True, slots=True)
class ContainerRunResult:
    """One infrastructure operation, separate from business verdicts.

    Preparation cleanup covers its verification container; the image remains owned
    until the campaign calls cleanup. Case cleanup covers only that case container.
    """

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
    """Docker resources live within one coordinator-owned campaign context."""

    def __init__(
        self,
        *,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300,
        verify_timeout_seconds: float = 60,
        run_timeout_seconds: float = 900,
        graceful_termination_seconds: float = 10,
    ) -> None:
        self.runtime = _validate_runtime(
            runtime_executable,
            (
                build_timeout_seconds,
                verify_timeout_seconds,
                run_timeout_seconds,
                graceful_termination_seconds,
            ),
        )
        self.build_timeout = build_timeout_seconds
        self.verify_timeout = verify_timeout_seconds
        self.run_timeout = run_timeout_seconds
        self.grace = graceful_termination_seconds
        self.run_id = uuid.uuid4().hex
        self.image_tag = f"install-sandbox-campaign:{self.run_id}"
        self.image_id: str | None = None
        self.build_attempted = False
        self.ready = False
        self.pending_containers: set[str] = set()
        self.interrupts = _SignalCapture()
        self.temporary: tempfile.TemporaryDirectory[str] | None = None
        self.logs: Path | None = None
        self.diagnostics = _DiagnosticTails()

    def __enter__(self) -> ContainerHarness:
        self.interrupts.__enter__()
        return self

    def __exit__(self, *_args: object) -> None:
        self.interrupts.__exit__()

    @property
    def interrupted(self) -> bool:
        return self.interrupts.signal_number is not None

    def prepare(self, subject_checkout: Path, output_directory: Path) -> ContainerRunResult:
        if self.logs is not None:
            raise ValueError("A harness prepares exactly one campaign image")
        subject_checkout = subject_checkout.expanduser().resolve(strict=True)
        if not subject_checkout.is_dir() or _paths_overlap(
            subject_checkout, output_directory.expanduser().resolve()
        ):
            raise ValueError("Preparation evidence must be separate from the subject directory")
        self.logs = _prepare_output(output_directory)
        records = [Timing(p) for p in ("copy_sources", "preflight", "build", "verify")]
        outcome = _Outcome("incomplete", "preflight", 2, "Preparation did not complete")
        try:
            outcome = self._prepare_image(subject_checkout, records)
        except Exception as error:
            outcome = _Outcome("incomplete", "build", 2, f"Preparation failed: {error}")
        self.ready = outcome.state == "completed" and not self.pending_containers
        return self._result(outcome, not self.pending_containers, records, self.run_id)

    def _prepare_image(self, subject: Path, records: list[Timing]) -> _Outcome:
        with measure(records[0]):
            self._check_temporary_parent(subject)
            self.temporary = tempfile.TemporaryDirectory(prefix=f"install-sandbox-{self.run_id}-")
            context = prepare_context(subject, Path(self.temporary.name))
        with measure(records[1]):
            result = self._command(
                [self.runtime, "version", "--format", "{{.Server.Version}}"],
                min(self.build_timeout, 10),
                "preflight",
            )
        failure = _command_failure(result, "preflight", "Docker daemon preflight failed")
        if failure is not None:
            return failure
        with measure(records[2]):
            failure = self._build_image(context)
        if failure is not None:
            return failure
        with measure(records[3]):
            verified = self._container(None, None, self.verify_timeout, "verify")
        return _Outcome(verified.state, verified.phase, verified.exit_code, verified.detail)

    def _check_temporary_parent(self, subject: Path) -> None:
        assert self.logs is not None
        parent = Path(tempfile.gettempdir()).resolve()
        if parent.is_relative_to(subject) or parent.is_relative_to(self.logs.parent):
            raise ValueError(
                "Temporary build context must be outside subject and campaign evidence"
            )

    def _build_image(self, context: Path) -> _Outcome | None:
        if self.interrupted:
            return _interrupted("build", self.interrupts.signal_number or signal.SIGINT)
        image_id_file = context.parent / "image-id"
        self.build_attempted = True
        result = self._command(
            [
                self.runtime,
                "build",
                "--progress=plain",
                "--file",
                str(context / "Containerfile"),
                "--tag",
                self.image_tag,
                "--iidfile",
                str(image_id_file),
                str(context),
            ],
            self.build_timeout,
            "build",
        )
        failure = _command_failure(result, "build", "Campaign image build failed")
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

    def run_case(self, *, case_file: Path, output_directory: Path) -> ContainerRunResult:
        if not self.ready:
            raise ValueError("Campaign image is not available")
        case = _resolve_case(case_file)
        output = output_directory.expanduser().resolve()
        if _paths_overlap(case, output) or any("," in str(p) for p in (case, output)):
            raise ValueError("Case and evidence mount paths must be separate and comma-free")
        output = _prepare_output(output_directory)
        return self._container(case, output, self.run_timeout, "run")

    def _container(
        self,
        case: Path | None,
        output: Path | None,
        timeout: float,
        phase: RunPhase,
    ) -> ContainerRunResult:
        run_id = uuid.uuid4().hex
        name = f"install-sandbox-case-{run_id}"
        records = [Timing(phase), Timing("cleanup")]
        self.diagnostics = _DiagnosticTails()
        outcome = _Outcome("incomplete", phase, 2, "Container did not complete")
        try:
            with measure(records[0]):
                outcome = self._launch(name, run_id, case, output, timeout, phase)
        except Exception as error:
            outcome = _Outcome("incomplete", phase, 2, f"Container failed: {error}")
        with measure(records[1]):
            clean = self._safe_cleanup_container(name)
        if self.interrupted:
            outcome = _interrupted(phase, self.interrupts.signal_number or signal.SIGINT)
        return self._result(_apply_cleanup(outcome, clean), clean, records, run_id)

    def _launch(
        self,
        name: str,
        run_id: str,
        case: Path | None,
        output: Path | None,
        timeout: float,
        phase: RunPhase,
    ) -> _Outcome:
        if self.interrupted:
            return _interrupted(phase, self.interrupts.signal_number or signal.SIGINT)
        self.pending_containers.add(name)
        result = self._command(self._run_command(name, run_id, case, output), timeout, phase)
        return _command_failure(result, phase, "Container failed") or _Outcome(
            "completed",
            "complete",
            0,
            "Container completed",
        )

    def _run_command(
        self,
        name: str,
        run_id: str,
        case: Path | None,
        output: Path | None,
    ) -> list[str]:
        assert self.image_id is not None
        command = [
            self.runtime,
            "run",
            "--rm",
            "--name",
            name,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            f"INSTALL_SANDBOX_RUN_ID={run_id}",
            "--env",
            f"INSTALL_SANDBOX_IMAGE_ID={self.image_id}",
            "--workdir",
            "/sandbox/work",
        ]
        if case is None:
            return [
                *command,
                "--entrypoint",
                "/opt/install-sandbox/venv/bin/graphify",
                self.image_id,
                "--help",
            ]
        assert output is not None
        return [
            *command,
            "--mount",
            _mount(case, "/sandbox/case.json", True),
            "--mount",
            _mount(output, "/sandbox/output", False),
            self.image_id,
            "--reference-sources",
            "/opt/install-sandbox/reference",
            "--prepared-executable",
            "/opt/install-sandbox/venv/bin/graphify",
            "--case-file",
            "/sandbox/case.json",
            "--output-directory",
            "/sandbox/output",
            "--work-directory",
            "/sandbox/work/case",
        ]

    def cleanup(self) -> ContainerRunResult:
        records = [Timing("cleanup")]
        clean = True
        outcome = _Outcome("completed", "complete", 0, "Campaign resources cleaned")
        with measure(records[0]):
            for name in tuple(self.pending_containers):
                clean = self._safe_cleanup_container(name) and clean
            try:
                clean = (not self.build_attempted or self._cleanup_image_tag()) and clean
            except Exception as error:
                outcome = _Outcome("incomplete", "cleanup", 2, f"Image cleanup failed: {error}")
                clean = False
            clean = self._cleanup_context() and clean
        self.ready = False
        if self.interrupted:
            outcome = _interrupted("cleanup", self.interrupts.signal_number or signal.SIGINT)
        return self._result(_apply_cleanup(outcome, clean), clean, records, self.run_id)

    def _cleanup_context(self) -> bool:
        try:
            if self.temporary is not None:
                self.temporary.cleanup()
            return True
        except OSError:
            return False

    def _safe_cleanup_container(self, name: str) -> bool:
        try:
            clean = name not in self.pending_containers or self._cleanup_container(name)
        except Exception:
            return False
        if clean:
            self.pending_containers.discard(name)
        return clean

    def _cleanup_container(self, name: str) -> bool:
        if self._container_absent(name):
            return True
        timeout = max(15.0, self.grace + 5.0)
        grace = str(max(1, math.ceil(self.grace)))
        self._cleanup_command(["stop", "--time", grace, name], timeout)
        if not self._container_absent(name):
            self._cleanup_command(["kill", name], timeout)
        if not self._container_absent(name):
            self._cleanup_command(["rm", "--force", name], timeout)
        return self._container_absent(name)

    def _container_absent(self, name: str) -> bool:
        result = self._cleanup_command(
            ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{name}$"],
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
            [self.runtime, *arguments], timeout, "cleanup", observe_interrupts=False
        )

    def _command(
        self,
        command: Sequence[str],
        timeout: float,
        phase: RunPhase,
        *,
        observe_interrupts: bool = True,
    ) -> _CommandResult:
        assert self.logs is not None
        with (self.logs / f"{phase}.log").open("a", encoding="utf-8") as log:
            log.write(f"Command: {list(command)!r}\n")
            log.flush()
            result = _execute_command(
                command,
                timeout,
                self.grace,
                self.interrupts if observe_interrupts else None,
                log,
            )
        self.diagnostics.add(phase, result)
        return result

    def _result(
        self,
        outcome: _Outcome,
        clean: bool,
        records: list[Timing],
        run_id: str,
    ) -> ContainerRunResult:
        skip_pending(records)
        return ContainerRunResult(
            run_id,
            outcome.state,
            outcome.phase,
            outcome.exit_code,
            self.image_id,
            clean,
            self.diagnostics.stdout.value,
            self.diagnostics.stderr.value,
            outcome.detail,
            records,
        )


def _validate_runtime(runtime: str | Path, budgets: Sequence[float]) -> str:
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("Campaigns must be called from the process main thread")
    if os.name != "posix":
        raise ValueError("Campaigns require a POSIX host with UID/GID support")
    if any(not math.isfinite(value) or value <= 0 for value in budgets):
        raise ValueError("Operational budgets must be finite and positive")
    if not str(runtime):
        raise ValueError("runtime_executable must not be empty")
    return str(Path(runtime).expanduser().resolve()) if "/" in str(runtime) else str(runtime)


def _resolve_case(case_file: Path) -> Path:
    try:
        resolved = case_file.expanduser().resolve(strict=True)
    except OSError as exc:
        raise _PreflightError(f"case_file is unavailable: {exc}") from exc
    if not resolved.is_file():
        raise _PreflightError("case_file must be a regular file")
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
    log: TextIO | None = None,
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
    return _observe_process(process, timeout_seconds, graceful_termination_seconds, interrupts, log)


def _observe_process(
    process: subprocess.Popen[str],
    timeout_seconds: float,
    graceful_termination_seconds: float,
    interrupts: _SignalCapture | None,
    log: TextIO | None = None,
) -> _CommandResult:
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_tail = _Tail()
    stderr_tail = _Tail()
    readers = [
        threading.Thread(target=_pump_stream, args=(process.stdout, sys.stdout, stdout_tail, log)),
        threading.Thread(target=_pump_stream, args=(process.stderr, sys.stderr, stderr_tail, log)),
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
        if interrupts is None:
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
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


def _pump_stream(
    source: TextIO,
    destination: TextIO,
    tail: _Tail,
    log: TextIO | None = None,
) -> None:
    for line in iter(source.readline, ""):
        tail.append(line)
        if log is not None:
            log.write(line)
            log.flush()
        try:
            destination.write(line)
            destination.flush()
        except (BrokenPipeError, OSError):
            pass
