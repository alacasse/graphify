"""Observed facts, verification diagnostics and durable local evidence."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from tools.install_sandbox.driver import InstallerCommandResult


class ObservationObstacle(TypedDict):
    operation: str
    root: str
    path: str
    reason: str


class SnapshotEntry(TypedDict):
    root: str
    path: str
    kind: str
    listing_complete: NotRequired[bool]
    content_file: NotRequired[str | None]
    sha256: NotRequired[str | None]


@dataclass
class FilesystemSnapshot:
    entries: list[SnapshotEntry] = field(default_factory=list[SnapshotEntry])
    obstacles: list[ObservationObstacle] = field(default_factory=list[ObservationObstacle])
    contents: dict[tuple[str, str], bytes] = field(default_factory=dict[tuple[str, str], bytes])

    def entry(self, root: str, path: str) -> SnapshotEntry | None:
        return next((e for e in self.entries if (e["root"], e["path"]) == (root, path)), None)

    def absent(self, root: str, path: str) -> bool:
        """An unlisted child is absent only under a completely listed parent."""
        if self.entry(root, path) is not None:
            return False
        parent = str(Path(path).parent)
        entry = self.entry(root, parent)
        if entry is not None:
            return entry["kind"] == "file" or (
                entry["kind"] == "directory" and entry.get("listing_complete", False)
            )
        return parent != path and self.absent(root, parent)


@dataclass(frozen=True)
class VerificationMismatch:
    type: str
    root: str
    path: str
    expected: str
    observed: str


@dataclass
class VerificationResult:
    complete: bool = True
    mismatches: list[VerificationMismatch] = field(default_factory=list[VerificationMismatch])
    obstacles: list[ObservationObstacle] = field(default_factory=list[ObservationObstacle])


class PreparationEvidence(TypedDict):
    ready: bool
    reason: str | None
    log: str


class CommandEvidence(TypedDict):
    args: list[str]
    cwd: str
    state: str
    exit_code: int | None
    reason: str | None
    stdout_file: str | None
    stderr_file: str | None


class StepEvidence(TypedDict):
    operation: str
    skip_reason: str | None
    command: CommandEvidence | None
    verification: VerificationResult | None
    observations: dict[str, str | None] | None


@dataclass
class InstallTestResult:
    case: dict[str, str]
    preparation: PreparationEvidence
    steps: list[StepEvidence]
    status: Literal["passed", "failed", "not_run", "incomplete"]
    evidence: dict[str, str | None]


class EvidenceWriteError(RuntimeError):
    """Evidence could not be saved; no completed result is promised."""


class TestResultWriter:
    """Persist facts and already established results; never calculate verdicts."""

    def __init__(self, output_directory: Path):
        self.output_directory = output_directory
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot create evidence directory: {error}") from error

    def write_snapshot(self, snapshot: FilesystemSnapshot, name: str) -> None:
        if name == "expected":
            try:
                (self.output_directory / "expected").mkdir(exist_ok=True)
            except OSError as error:
                raise EvidenceWriteError(
                    f"Cannot create expected evidence directory: {error}"
                ) from error
        for entry in snapshot.entries:
            key = (entry["root"], entry["path"])
            if key in snapshot.contents:
                prefix = "expected" if name == "expected" else f"steps/0/{name}/{key[0]}"
                relative = f"{prefix}/{key[1]}"
                self._write_bytes(relative, snapshot.contents[key])
                entry["content_file"] = relative
        relative = "expected.json" if name == "expected" else f"steps/0/{name}.json"
        self._write_json(relative, {"entries": snapshot.entries, "obstacles": snapshot.obstacles})

    def write_verification(self, result: VerificationResult) -> None:
        self._write_json("steps/0/verification.json", asdict(result))

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

    def write_command(self, result: InstallerCommandResult) -> CommandEvidence:
        self._write_bytes("steps/0/stdout.txt", result.stdout)
        self._write_bytes("steps/0/stderr.txt", result.stderr)
        return {
            "args": result.args,
            "cwd": result.cwd,
            "state": result.state,
            "exit_code": result.exit_code,
            "reason": result.reason,
            "stdout_file": "steps/0/stdout.txt",
            "stderr_file": "steps/0/stderr.txt",
        }

    def write_result(self, result: InstallTestResult) -> None:
        self._write_json("result.json.tmp", asdict(result))
        try:
            (self.output_directory / "result.json.tmp").replace(
                self.output_directory / "result.json"
            )
        except OSError as error:
            raise EvidenceWriteError(f"Cannot finalize result.json: {error}") from error
