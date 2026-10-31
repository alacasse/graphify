"""Write case results and retained evidence inside the container."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING

from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
    CheckpointReceipt,
    CommandEvidence,
    EvidenceWriteError,
    InstallTestResult,
    SnapshotEntry,
    VerificationResult,
)
from tools.install_sandbox.contracts.timings import (
    Timing,
    case_timings,
    elapsed,
    measure,
    skip_pending,
)
from tools.install_sandbox.rules.repair_actions import (
    JsonArtifact,
    SnapshotArtifact,
    artifact_digest,
)
from tools.install_sandbox.rules.repair_protocol import (
    PendingCheckpoint,
    checkpoint_digest,
)

if TYPE_CHECKING:
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot


class TestResultWriter:
    """Persist facts and already established results; never calculate verdicts."""

    def __init__(self, output_directory: Path):
        self.output_directory = output_directory
        self.halted = False
        self.timings: list[Timing] = []
        self.timing_diagnostics: list[str] = []
        self.timing_duration: float | None = None
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot create evidence directory: {error}") from error

    def retain(self, artifact: JsonArtifact | SnapshotArtifact) -> ArtifactReceipt:
        """Retain a protocol-encoded transport and verify the persisted bytes."""
        if self.halted:
            raise EvidenceWriteError("Evidence writer has halted")
        relative = artifact.reference
        path = self.output_directory / relative
        if not path.resolve().is_relative_to(self.output_directory.resolve()):
            raise EvidenceWriteError("Artifact escaped the evidence directory")
        if isinstance(artifact, JsonArtifact):
            self._write_json(relative, artifact.document)
        else:
            self._snapshot(artifact.snapshot, relative.removesuffix(".json"))
        if path.is_symlink() or not path.is_file():
            raise EvidenceWriteError("Artifact has not been retained")
        if isinstance(artifact, SnapshotArtifact):
            self._check_snapshot_receipt(path, artifact.snapshot, relative.removesuffix(".json"))
        elif artifact_digest(json.loads(path.read_bytes())) != artifact_digest(artifact):
            raise EvidenceWriteError("Published artifact differs from retained facts")
        return ArtifactReceipt(relative, artifact_digest(artifact))

    def _check_snapshot_receipt(self, path: Path, payload: FilesystemSnapshot, prefix: str) -> None:
        expected = self._manifest(payload, prefix)
        for entry in expected["entries"]:
            content = entry.get("content_file")
            if (
                content is not None
                and (self.output_directory / content).read_bytes()
                != (payload.contents[(entry["root"], entry["path"])])
            ):
                raise EvidenceWriteError("Published snapshot differs from retained facts")
        if json.loads(path.read_bytes()) != {**expected, "obstacles": payload.obstacles}:
            raise EvidenceWriteError("Published manifest differs from retained facts")

    def write_checkpoint(
        self, result: InstallTestResult, pending: PendingCheckpoint
    ) -> CheckpointReceipt:
        if self.halted:
            raise EvidenceWriteError("Evidence writer has halted")
        candidate = replace(
            result, intermediate_preparation=dict(pending.checkpoint), status=pending.status
        )
        self.write_result(candidate)
        result.intermediate_preparation = candidate.intermediate_preparation
        result.status = candidate.status
        published = json.loads((self.output_directory / "result.json").read_bytes())
        return CheckpointReceipt(
            pending.session_id,
            pending.generation,
            checkpoint_digest(published["intermediate_preparation"], published["status"]),
        )

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

    @staticmethod
    def _manifest(snapshot: FilesystemSnapshot, prefix: str) -> dict[str, list[SnapshotEntry]]:
        entries: list[SnapshotEntry] = []
        for entry in snapshot.entries:
            retained = entry.copy()
            retained.pop("content_file", None)
            retained.pop("sha256", None)
            key = (entry["root"], entry["path"])
            if key in snapshot.contents:
                relative = (
                    f"{prefix}/{key[1]}" if prefix == "expected" else f"{prefix}/{key[0]}/{key[1]}"
                )
                retained["content_file"] = relative
                retained["sha256"] = hashlib.sha256(snapshot.contents[key]).hexdigest()
            entries.append(retained)
        return {"entries": entries}

    def _snapshot(self, snapshot: FilesystemSnapshot, prefix: str) -> None:
        manifest = self._manifest(snapshot, prefix)
        for entry in manifest["entries"]:
            relative = entry.get("content_file")
            if relative is not None:
                self._write_bytes(relative, snapshot.contents[(entry["root"], entry["path"])])
        self._write_json(f"{prefix}.json", {**manifest, "obstacles": snapshot.obstacles})

    def write_metadata(self, relative: str, value: object) -> None:
        self._write_json(relative, value)

    def write_initial_verification(self, result: VerificationResult) -> None:
        self._write_json("initial-verification.json", asdict(result))

    def write_verification(self, result: VerificationResult, *, step_index: int = 0) -> None:
        self._write_json(f"steps/{step_index}/verification.json", asdict(result))

    def _write_json(self, relative: str, value: object) -> None:
        destination = self.output_directory / relative
        temporary: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, indent=2)
                stream.write("\n")
            temporary.replace(destination)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot publish evidence {relative}: {error}") from error
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

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
        self._write_json("result.json", asdict(result))
