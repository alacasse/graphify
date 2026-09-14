"""Prepare isolated witnesses and capture observations without running Graphify."""

from __future__ import annotations

import hashlib
import json
import posixpath
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools.install_sandbox.contracts.case import InstallTestCase, destinations
from tools.install_sandbox.contracts.results import (
    FileAlterationPlan,
    ObservationObstacle,
    ReferenceRepairPlan,
    SkillBackupPlan,
    SnapshotEntry,
)

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


def reference_repair_plan(
    case: InstallTestCase, expected: FilesystemSnapshot
) -> tuple[ReferenceRepairPlan, bytes]:
    """Select from retained source files, never from the installed inventory."""
    source = case.spec.references_source + "/"
    files = sorted(
        e["path"]
        for e in expected.entries
        if e["root"] == "subject" and e["kind"] == "file" and e["path"].startswith(source)
    )
    if expected.obstacles or len(files) < 2:
        raise ValueError("Reference repair requires at least two fully observed source files")
    content = expected.contents.get(("subject", files[1]))
    if content is None:
        raise ValueError("Reference repair source content unavailable")
    destination = destinations(case)["references"] + "/"
    return {
        "deleted_path": destination + files[0][len(source) :],
        "altered_path": destination + files[1][len(source) :],
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content + b"\nSandbox repair witness.\n"


def skill_repair_plan(
    case: InstallTestCase, expected: FilesystemSnapshot
) -> tuple[FileAlterationPlan, bytes]:
    """Retain the exact skill alteration independently of installed contents."""
    content = expected.contents[("subject", case.spec.skill_source)]
    return {
        "altered_path": destinations(case)["skill"],
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content + b"\nSandbox skill repair witness.\n"


def skill_backup_plan(
    case: InstallTestCase, expected: FilesystemSnapshot
) -> tuple[SkillBackupPlan, bytes]:
    """Build the backup witness from retained sources, independently of installed files."""
    content = expected.contents[("subject", case.spec.skill_source)]
    return {
        "backup_path": destinations(case)["skill"] + ".bak",
        "backup_content_file": "steps/1/preparation/backup-content.bin",
    }, content + b"\nSandbox previous backup witness.\n"


def _obstacle(
    snapshot: FilesystemSnapshot, operation: str, root: str, path: str, error: OSError | str
) -> None:
    snapshot.obstacles.append(
        {"operation": operation, "root": root, "path": path, "reason": str(error)}
    )


class TestEnvironment:
    """Own fresh project/home directories; software and evidence stay outside them."""

    def __init__(self, case: InstallTestCase, directory: Path):
        self.case = InstallTestCase.from_json(case.to_json())
        self.project = directory / "project"
        self.home = directory / "home"
        self.project.mkdir(parents=True, exist_ok=False)
        self.home.mkdir(parents=True, exist_ok=False)

    def prepare(self) -> None:
        for initial in self.case.initial_files:
            root = self.project if initial["root"] == "project" else self.home
            path = root / initial["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(initial["content"].encode("utf-8"))

    def prepare_reference_repair(self, plan: ReferenceRepairPlan, content: bytes) -> str | None:
        """Leave partial effects in place so the next observation can retain them."""
        try:
            (self.project / plan["deleted_path"]).unlink()
            (self.project / plan["altered_path"]).write_bytes(content)
        except OSError as error:
            return f"Reference repair preparation failed: {error}"
        return None

    def prepare_skill_repair(self, plan: FileAlterationPlan, content: bytes) -> str | None:
        """Preserve a failed write's partial effects for observation."""
        try:
            (self.project / plan["altered_path"]).write_bytes(content)
        except OSError as error:
            return f"Skill repair preparation failed: {error}"
        return None

    def prepare_markdown_repair(self, plan: FileAlterationPlan, content: bytes) -> str | None:
        """Keep partial writes observable when the shared document cannot be prepared."""
        try:
            (self.project / plan["altered_path"]).write_bytes(content)
        except OSError as error:
            return f"Markdown repair preparation failed: {error}"
        return None

    def prepare_json_repair(self, plan: FileAlterationPlan) -> str | None:
        """Remove only the registration from the installed JSON, retaining partial effects."""
        try:
            path = self.project / plan["altered_path"]
            settings: object = json.loads(path.read_bytes())
            if not isinstance(settings, dict):
                raise ValueError("Expected JSON object")
            settings = cast(dict[str, object], settings)
            items = settings.get(self.case.spec.json_list)
            if not isinstance(items, list):
                raise ValueError("Expected instruction list")
            items = cast(list[object], items)
            entry = posixpath.relpath(
                destinations(self.case)["skill"], posixpath.dirname(plan["altered_path"])
            )
            if items.count(entry) != 1:
                raise ValueError("Expected exactly one skill instruction before deletion")
            items.remove(entry)
            path.write_bytes((json.dumps(settings, indent=2) + "\n").encode("utf-8"))
        except (OSError, ValueError, UnicodeError) as error:
            return f"JSON repair preparation failed: {error}"
        return None

    def prepare_skill_backup(self, plan: SkillBackupPlan, content: bytes) -> str | None:
        """Keep any partial write observable if preparing the backup fails."""
        try:
            (self.project / plan["backup_path"]).write_bytes(content)
        except OSError as error:
            return f"Skill backup preparation failed: {error}"
        return None

    def observe(
        self, writer: TestResultWriter, phase: str, *, step_index: int = 0
    ) -> FilesystemSnapshot:
        if phase not in {"before", "after"}:
            raise ValueError("Observation phase must be before or after")
        snapshot = FilesystemSnapshot()
        for root, directory in (("project", self.project), ("home", self.home)):
            self._capture(snapshot, root, directory, ".", expected=False)
        writer.write_snapshot(snapshot, phase, step_index=step_index)
        return snapshot

    def preserve_expected(self, subject: Path, writer: TestResultWriter) -> FilesystemSnapshot:
        snapshot = FilesystemSnapshot()
        spec = self.case.spec
        for path in (spec.skill_source, spec.markdown_source, spec.references_source):
            self._capture(snapshot, "subject", subject, path, expected=True)
        writer.write_snapshot(snapshot, "expected")
        return snapshot

    def _capture(
        self,
        snapshot: FilesystemSnapshot,
        root: str,
        directory: Path,
        relative: str,
        *,
        expected: bool,
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
            self._directory(snapshot, entry, directory, expected=expected)
        elif stat.S_ISREG(mode):
            entry["kind"] = "file"
            self._file(snapshot, entry, path, expected=expected)
        else:
            entry["kind"] = "other"
            _obstacle(snapshot, "observe_entry", root, relative, "Unsupported filesystem entry")

    def _directory(
        self, snapshot: FilesystemSnapshot, entry: SnapshotEntry, directory: Path, *, expected: bool
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
                expected=expected,
            )

    def _file(
        self, snapshot: FilesystemSnapshot, entry: SnapshotEntry, path: Path, *, expected: bool
    ) -> None:
        dest = destinations(self.case)
        if (
            not expected
            and self.case.name == "first-install"
            and entry["root"] == "project"
            and entry["path"] == dest["version"]
        ):
            return
        keep = expected or self._keep_content(entry, dest)
        if keep:
            entry["content_file"] = None
        else:
            entry["sha256"] = None
        try:
            content = path.read_bytes()
        except OSError as error:
            _obstacle(snapshot, "read_file", entry["root"], entry["path"], error)
            return
        if keep:
            snapshot.contents[(entry["root"], entry["path"])] = content
        else:
            entry["sha256"] = hashlib.sha256(content).hexdigest()

    def _keep_content(self, entry: SnapshotEntry, dest: dict[str, str]) -> bool:
        witnesses = {(f["root"], f["path"]) for f in self.case.initial_files}
        if (entry["root"], entry["path"]) in witnesses:
            return True
        return entry["root"] == "project" and (
            entry["path"] in (dest["skill"], dest["markdown"], dest["json"], dest["version"])
            or (
                self.case.name in {"repair-skill", "preserve-skill-backup"}
                and entry["path"] == dest["skill"] + ".bak"
            )
            or entry["path"].startswith(dest["references"] + "/")
        )
