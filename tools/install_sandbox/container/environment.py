"""Prepare isolated witnesses and capture observations without running Graphify."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING

from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry

if TYPE_CHECKING:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter


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
            # A successfully lstat-ed nonregular entry is a complete physical fact.

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
