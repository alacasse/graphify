"""Write case results and retained evidence inside the container."""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.effect_case import unique_object
from tools.install_sandbox.contracts.evidence_layout import (
    SnapshotPublication,
    plan_json,
    plan_snapshot,
)
from tools.install_sandbox.contracts.results import (
    ArtifactReceipt,
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
from tools.install_sandbox.rules.repair_actions import (
    JsonArtifact,
    SnapshotArtifact,
    artifact_digest,
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
        snapshot_plan = (
            plan_snapshot(relative, artifact.snapshot)
            if isinstance(artifact, SnapshotArtifact)
            else None
        )
        if isinstance(artifact, JsonArtifact):
            self._write_json(relative, artifact.document)
        elif snapshot_plan is not None:
            self._snapshot(snapshot_plan)
        if path.is_symlink() or not path.is_file():
            raise EvidenceWriteError("Artifact has not been retained")
        if snapshot_plan is not None:
            self._check_snapshot_receipt(path, snapshot_plan)
        elif artifact_digest(json.loads(path.read_bytes())) != artifact_digest(artifact):
            raise EvidenceWriteError("Published artifact differs from retained facts")
        return ArtifactReceipt(relative, artifact_digest(artifact))

    def _read_regular(self, path: Path) -> bytes:
        if path.resolve() != path.absolute() or not path.is_file():
            raise EvidenceWriteError(f"Missing regular evidence file: {path.name}")
        return path.read_bytes()

    def _check_json(self, path: Path, expected: object) -> None:
        document = json.loads(self._read_regular(path), object_pairs_hook=unique_object)
        if artifact_digest(document) != artifact_digest(expected):
            raise EvidenceWriteError(f"Retained document contradicts its receipt: {path.name}")

    def _check_snapshot_receipt(self, path: Path, plan: SnapshotPublication) -> None:
        for reference, content in plan.blobs:
            if self._read_regular(self.output_directory / reference) != content:
                raise EvidenceWriteError("Published snapshot differs from retained facts")
        self._check_json(path, plan.manifest.document)

    def verify_inputs(
        self, reference: str, expected: object, before_reference: str, before: FilesystemSnapshot
    ) -> None:
        try:
            self._check_json(self.output_directory / reference, expected)
            self._check_snapshot_receipt(
                self.output_directory / before_reference, plan_snapshot(before_reference, before)
            )
        except (OSError, ValueError) as error:
            raise EvidenceWriteError(f"Cannot verify command inputs: {error}") from error

    def verify_receipt(
        self,
        index: int,
        command: InstallerCommandResult,
        after: FilesystemSnapshot,
        verdict: VerificationResult,
    ) -> None:
        """Only the process outputs and observations actually retained may authorize dependents."""
        directory = self.output_directory / "steps" / str(index)
        reference = f"steps/{index}/after.json"
        try:
            self._check_snapshot_receipt(directory / "after.json", plan_snapshot(reference, after))
            self._check_json(directory / "verification.json", asdict(verdict))
            self._check_json(directory / "environment.json", command.environment)
            for name, expected in (("stdout.txt", command.stdout), ("stderr.txt", command.stderr)):
                if self._read_regular(directory / name) != expected:
                    raise EvidenceWriteError(
                        f"Retained command stream contradicts its receipt: {name}"
                    )
        except (OSError, ValueError) as error:
            raise EvidenceWriteError(f"Cannot verify command receipt: {error}") from error

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
                self.halted = True
                raise EvidenceWriteError(
                    f"Cannot create expected evidence directory: {error}"
                ) from error
        prefix = "expected" if name == "expected" else f"steps/{step_index}/{name}"
        self._snapshot(plan_snapshot(f"{prefix}.json", snapshot))

    def _snapshot(self, plan: SnapshotPublication) -> None:
        for reference, content in plan.blobs:
            self._write_bytes(reference, content)
        self._write_json(plan.manifest.reference, plan.manifest.document)

    def write_metadata(self, relative: str, value: object) -> None:
        self._write_json(relative, value)

    def write_initial_verification(self, result: VerificationResult) -> None:
        self._write_json("initial-verification.json", asdict(result))

    def write_initial_observation(self, snapshot: FilesystemSnapshot) -> None:
        self._snapshot(plan_snapshot("initial/before.json", snapshot))

    def write_verification(self, result: VerificationResult, *, step_index: int = 0) -> None:
        self._write_json(f"steps/{step_index}/verification.json", asdict(result))

    def _write_json(self, relative: str, value: object) -> None:
        authoritative = relative != "timings.json.tmp"
        if self.halted and authoritative:
            raise EvidenceWriteError("Evidence writer has halted")
        plan = plan_json(relative, value)
        destination = self.output_directory / plan.reference
        temporary: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=plan.temporary_prefix,
                suffix=plan.temporary_suffix,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(plan.document, stream, indent=2)
                stream.write("\n")
            temporary.replace(destination)
        except OSError as error:
            if authoritative:
                self.halted = True
            raise EvidenceWriteError(f"Cannot publish evidence {relative}: {error}") from error
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def _write_bytes(self, relative: str, content: bytes, *, append: bool = False) -> None:
        if self.halted:
            raise EvidenceWriteError("Evidence writer has halted")
        destination = self.output_directory / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("ab" if append else "wb") as stream:
                stream.write(content)
        except OSError as error:
            self.halted = True
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
        return result.evidence(f"steps/{step_index}/stdout.txt", f"steps/{step_index}/stderr.txt")

    def write_result(self, result: InstallTestResult) -> None:
        self._write_json("result.json", result_document(result))


def result_document(result: InstallTestResult) -> dict[str, object]:
    document = asdict(result)
    document["preparation"] = result.preparation.to_data()
    document["steps"] = [step.to_data() for step in result.steps]
    return document
