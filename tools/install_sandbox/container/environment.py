"""Prepare isolated witnesses and capture observations without running Graphify."""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tools.install_sandbox.contracts.results import ObservationObstacle, SnapshotEntry

if TYPE_CHECKING:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter


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


def _obstacle(
    snapshot: FilesystemSnapshot, operation: str, root: str, path: str, error: OSError | str
) -> None:
    snapshot.obstacles.append(
        {"operation": operation, "root": root, "path": path, "reason": str(error)}
    )


class ObservedEnvironment:
    """Capture project/home trees for both case representations, retaining file bytes."""

    project: Path
    home: Path

    def observe(
        self, writer: TestResultWriter, phase: str, *, step_index: int = 0
    ) -> FilesystemSnapshot:
        if phase not in {"before", "after"}:
            raise ValueError("Observation phase must be before or after")
        snapshot = FilesystemSnapshot()
        for root, directory in (("project", self.project), ("home", self.home)):
            self._capture(snapshot, root, directory, ".")
        writer.write_snapshot(snapshot, phase, step_index=step_index)
        return snapshot

    def _capture(
        self,
        snapshot: FilesystemSnapshot,
        root: str,
        directory: Path,
        relative: str,
    ) -> None:
        path = directory / relative
        entry: SnapshotEntry = {"root": root, "path": relative, "kind": "unknown"}
        snapshot.entries.append(entry)
        try:
            mode = path.lstat().st_mode
        except OSError as error:
            _obstacle(snapshot, "stat", root, relative, error)
            return
        if stat.S_ISDIR(mode):
            entry["kind"] = "directory"
            self._directory(snapshot, entry, directory)
        elif stat.S_ISREG(mode):
            entry["kind"] = "file"
            self._file(snapshot, entry, path)
        else:
            entry["kind"] = "other"
            _obstacle(snapshot, "observe_entry", root, relative, "Unsupported filesystem entry")

    def _directory(
        self, snapshot: FilesystemSnapshot, entry: SnapshotEntry, directory: Path
    ) -> None:
        entry["listing_complete"] = False
        try:
            children = sorted((directory / entry["path"]).iterdir())
        except OSError as error:
            _obstacle(snapshot, "list_directory", entry["root"], entry["path"], error)
            return
        entry["listing_complete"] = True
        for child in children:
            self._capture(
                snapshot,
                entry["root"],
                directory,
                str(child.relative_to(directory)),
            )

    def _file(self, snapshot: FilesystemSnapshot, entry: SnapshotEntry, path: Path) -> None:
        entry["content_file"] = None
        try:
            snapshot.contents[(entry["root"], entry["path"])] = path.read_bytes()
        except OSError as error:
            _obstacle(snapshot, "read_file", entry["root"], entry["path"], error)
