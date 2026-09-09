"""Observed facts, verification diagnostics and durable local evidence."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import NotRequired, TypedDict


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


class TestResultWriter:
    """Persist facts and already established results; never calculate verdicts."""

    def __init__(self, output_directory: Path):
        self.output_directory = output_directory
        output_directory.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, snapshot: FilesystemSnapshot, name: str) -> None:
        for entry in snapshot.entries:
            key = (entry["root"], entry["path"])
            if key in snapshot.contents:
                prefix = "expected" if name == "expected" else f"steps/0/{name}/{key[0]}"
                relative = f"{prefix}/{key[1]}"
                destination = self.output_directory / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(snapshot.contents[key])
                entry["content_file"] = relative
        relative = "expected.json" if name == "expected" else f"steps/0/{name}.json"
        self._write_json(relative, {"entries": snapshot.entries, "obstacles": snapshot.obstacles})

    def write_verification(self, result: VerificationResult) -> None:
        self._write_json("steps/0/verification.json", asdict(result))

    def _write_json(self, relative: str, value: object) -> None:
        destination = self.output_directory / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
