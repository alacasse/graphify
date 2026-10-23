"""Write case results and retained evidence inside the container."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    EvidenceWriteError,
    InstallTestResult,
    VerificationResult,
)
from tools.install_sandbox.contracts.timings import (
    Timing,
    case_timings,
    elapsed,
    measure,
    skip_pending,
)

if TYPE_CHECKING:
    from tools.install_sandbox.container.environment import FilesystemSnapshot


class TestResultWriter:
    """Persist facts and already established results; never calculate verdicts."""

    def __init__(self, output_directory: Path):
        self.output_directory = output_directory
        self.timings: list[Timing] = []
        self.timing_diagnostics: list[str] = []
        self.timing_duration: float | None = None
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot create evidence directory: {error}") from error

    def initialize_timings(self, case_name: str, step_count: int) -> None:
        self.timings = case_timings(case_name, step_count)

    @contextmanager
    def measure(self, phase: str, step: int | None = None) -> Generator[Timing]:
        record = next(r for r in self.timings if (r.phase, r.step) == (phase, step))
        record.state = "running"
        self._save_timings()
        try:
            with measure(record):
                yield record
        finally:
            self._save_timings()

    def finish_timings(self, started_ns: int) -> None:
        skip_pending(self.timings)
        self.timing_duration = elapsed(started_ns)
        self._save_timings()

    def _save_timings(self) -> None:
        if self.timing_diagnostics:
            return
        payload = {
            "version": 2,
            "duration_seconds": self.timing_duration,
            "phases": [asdict(record) for record in self.timings],
        }
        try:
            self._write_json("timings.json.tmp", payload)
            (self.output_directory / "timings.json.tmp").replace(
                self.output_directory / "timings.json"
            )
        except (EvidenceWriteError, OSError) as error:
            diagnostic = f"Timing evidence unavailable: {error}"
            self.timing_diagnostics.append(diagnostic)
            with suppress(OSError):
                print(diagnostic, file=sys.stderr)

    def write_snapshot(
        self, snapshot: FilesystemSnapshot, name: str, *, step_index: int = 0
    ) -> None:
        if name == "expected":
            try:
                (self.output_directory / "expected").mkdir(exist_ok=True)
            except OSError as error:
                raise EvidenceWriteError(
                    f"Cannot create expected evidence directory: {error}"
                ) from error
        prefix = "expected" if name == "expected" else f"steps/{step_index}/{name}"
        self._snapshot(snapshot, prefix)

    def write_intermediate_snapshot(self, snapshot: FilesystemSnapshot, name: str) -> None:
        if name not in {"before", "after"}:
            raise ValueError("Invalid intermediate observation phase")
        self._snapshot(snapshot, f"intermediate/{name}")

    def _snapshot(self, snapshot: FilesystemSnapshot, prefix: str) -> None:
        for entry in snapshot.entries:
            key = (entry["root"], entry["path"])
            if key in snapshot.contents:
                relative = (
                    f"{prefix}/{key[1]}" if prefix == "expected" else f"{prefix}/{key[0]}/{key[1]}"
                )
                self._write_bytes(relative, snapshot.contents[key])
                entry["content_file"] = relative
                entry["sha256"] = hashlib.sha256(snapshot.contents[key]).hexdigest()
        self._write_json(
            f"{prefix}.json", {"entries": snapshot.entries, "obstacles": snapshot.obstacles}
        )

    def write_metadata(self, relative: str, value: object) -> None:
        self._write_json(relative, value)

    def write_initial_verification(self, result: VerificationResult) -> None:
        self._write_json("initial-verification.json", asdict(result))

    def write_verification(self, result: VerificationResult, *, step_index: int = 0) -> None:
        self._write_json(f"steps/{step_index}/verification.json", asdict(result))

    def _write_json(self, relative: str, value: object) -> None:
        self._write_bytes(relative, (json.dumps(value, indent=2) + "\n").encode("utf-8"))

    def _write_bytes(self, relative: str, content: bytes, *, append: bool = False) -> None:
        destination = self.output_directory / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("ab" if append else "wb") as stream:
                stream.write(content)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot write evidence {relative}: {error}") from error

    def append_log(self, relative: str, message: str | bytes) -> None:
        content = message.encode("utf-8") if isinstance(message, str) else message
        self._write_bytes(relative, content, append=True)

    def write_command(
        self, result: InstallerCommandResult, *, step_index: int = 0
    ) -> CommandEvidence:
        if result.environment is not None:
            self._write_json(f"steps/{step_index}/environment.json", result.environment)
        self._write_bytes(f"steps/{step_index}/stdout.txt", result.stdout)
        self._write_bytes(f"steps/{step_index}/stderr.txt", result.stderr)
        return {
            "args": result.args,
            "cwd": result.cwd,
            "state": result.state,
            "exit_code": result.exit_code,
            "reason": result.reason,
            "stdout_file": f"steps/{step_index}/stdout.txt",
            "stderr_file": f"steps/{step_index}/stderr.txt",
        }

    def write_result(self, result: InstallTestResult) -> None:
        self._write_json("result.json.tmp", asdict(result))
        try:
            (self.output_directory / "result.json.tmp").replace(
                self.output_directory / "result.json"
            )
        except OSError as error:
            raise EvidenceWriteError(f"Cannot finalize result.json: {error}") from error
