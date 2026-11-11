"""Shared decoding and binding of retained filesystem and command evidence."""

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import cast

from tools.install_sandbox.contracts.evidence_layout import blob_reference
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    SnapshotEntry,
    parse_obstacle,
)
from tools.install_sandbox.contracts.spec import fields, relative_path, text

_ENTRY_FIELDS = {"root", "path", "kind"}
_KIND_FIELDS: dict[str, set[str]] = {
    "file": {"content_file", "sha256"},
    "directory": {"listing_complete"},
    "unknown": set(),
    "other": set(),
}


def safe_evidence_path(output_directory: Path, relative: str) -> Path:
    """Resolve a result-relative evidence reference without leaving its directory."""
    relative_path(relative.removesuffix("/"))
    root = output_directory.absolute()
    for candidate in (root, *root.parents):
        if candidate.is_symlink():
            raise ValueError("Evidence directory contains a symlink")
    destination = root
    for part in PurePosixPath(relative).parts:
        destination /= part
        if destination.is_symlink():
            raise ValueError(f"Evidence path contains a symlink: {relative!r}")
    if not destination.is_relative_to(root) or destination == root:
        raise ValueError(f"Evidence path escapes the result directory: {relative!r}")
    return destination


def json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"Duplicate result field: {key}")
        data[key] = value
    return data


def json_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return cast(list[object], value)


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean")
    return value


def optional_text(value: object) -> str | None:
    return None if value is None else text(value)


def read_json_evidence(output: Path, relative: str) -> object:
    return json.loads(
        safe_evidence_path(output, relative).read_bytes(), object_pairs_hook=json_object
    )


def check_snapshot(
    output: Path,
    relative: str,
    *,
    complete: bool = True,
    presence_only: tuple[str, str] | None = None,
) -> list[dict[str, object]]:
    """Validate inventory and content bindings, without deciding file conformance."""
    data = fields(read_json_evidence(output, relative), "entries obstacles")
    for obstacle in json_list(data["obstacles"]):
        parse_obstacle(obstacle)
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for value in json_list(data["entries"]):
        entry = snapshot_entry(value, output, relative)
        key = (text(entry["root"]), text(entry["path"]))
        if key in seen:
            raise ValueError("Duplicate snapshot entry")
        seen.add(key)
        entries.append(entry)
    if complete:
        check_complete_snapshot(entries, json_list(data["obstacles"]), presence_only)
    return entries


def check_complete_snapshot(
    entries: list[dict[str, object]],
    obstacles: list[object],
    presence_only: tuple[str, str] | None = None,
) -> None:
    if obstacles or not entries:
        raise ValueError("Complete verification requires observable snapshot evidence")
    for entry in entries:
        kind = entry["kind"]
        if kind == "file" and (entry["root"], entry["path"]) == presence_only:
            continue
        if kind == "file" and entry.get("content_file") is None and entry.get("sha256") is None:
            raise ValueError("Complete verification requires file content evidence")
        if kind == "directory" and entry.get("listing_complete") is not True:
            raise ValueError("Complete verification requires complete directory listings")
        if kind not in {"file", "directory"}:
            raise ValueError("Complete verification contradicts unsupported entry")


def snapshot_entry(value: object, output: Path, reference: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid snapshot entry")
    entry = cast(dict[str, object], value)
    if not _ENTRY_FIELDS.issubset(entry):
        raise ValueError("Invalid snapshot entry fields")
    root, path, kind = text(entry["root"]), text(entry["path"]), text(entry["kind"])
    if path != ".":
        relative_path(path)
    if root not in ({"subject"} if reference == "expected.json" else {"project", "home"}):
        raise ValueError("Invalid snapshot root")
    allowed = _KIND_FIELDS.get(kind)
    if allowed is None:
        raise ValueError("Invalid snapshot entry kind")
    forbidden = entry.keys() - _ENTRY_FIELDS - allowed
    if forbidden:
        raise ValueError(
            f"Snapshot {root}/{path} kind {kind} forbids fields: {', '.join(sorted(forbidden))}"
        )
    if "listing_complete" in entry:
        boolean(entry["listing_complete"])
    check_content_binding(entry, output, reference)
    return entry


def check_content_binding(entry: dict[str, object], output: Path, reference: str) -> None:
    root, path = text(entry["root"]), text(entry["path"])
    if entry.get("content_file") is not None:
        binding = blob_reference(reference, root, path)
        if entry["content_file"] != binding:
            raise ValueError("Snapshot content must belong to its own observation")
        safe_evidence_path(output, binding).read_bytes()


def retained_snapshot(output: Path, relative: str) -> FilesystemSnapshot:
    data = fields(read_json_evidence(output, relative), "entries obstacles")
    entries = check_snapshot(output, relative, complete=False)
    snapshot = FilesystemSnapshot(
        entries=[cast(SnapshotEntry, entry) for entry in entries],
        obstacles=[parse_obstacle(o) for o in json_list(data["obstacles"])],
    )
    for entry in snapshot.entries:
        content = entry.get("content_file")
        if content is not None:
            retained = safe_evidence_path(output, content).read_bytes()
            if entry.get("sha256") not in {None, hashlib.sha256(retained).hexdigest()}:
                raise ValueError("Retained content contradicts its snapshot digest")
            snapshot.contents[(entry["root"], entry["path"])] = retained
    return snapshot


def check_environment(command: CommandEvidence, output: Path, index: int) -> None:
    """Bind allowlisted execution settings to the case's isolated roots."""
    cwd = PurePosixPath(command["cwd"])
    if not cwd.is_absolute() or cwd.name != "project" or ".." in cwd.parts:
        raise ValueError("Command requires a canonical isolated project directory")
    home = cwd.parent / "home"
    temporary = cwd.parent.parent / "command-tmp"
    names = (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "APPDATA",
        "LOCALAPPDATA",
    )
    expected = {
        "PATH": "/bin:/usr/bin",
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "USERPROFILE": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        **{name: str(temporary / "configuration" / name.lower()) for name in names},
    }
    if read_json_evidence(output, f"steps/{index}/environment.json") != expected:
        raise ValueError("Execution environment contradicts isolated case roots or allowlist")
