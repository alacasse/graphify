"""Shared decoding and binding of retained filesystem and command evidence."""

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import cast

from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    ObservationObstacle,
    SnapshotEntry,
    VerificationMismatch,
    VerificationResult,
)
from tools.install_sandbox.contracts.spec import fields, relative_path, text


def safe_evidence_path(output_directory: Path, relative: str) -> Path:
    """Resolve a result-relative evidence reference without leaving its directory."""
    relative_path(relative.removesuffix("/"))
    root = output_directory.resolve()
    try:
        destination = (root / relative).resolve()
    except RuntimeError as error:
        raise ValueError(f"Cannot resolve evidence path: {relative!r}") from error
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


def string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


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


def parse_obstacle(value: object) -> ObservationObstacle:
    data = fields(value, "operation root path reason")
    return {
        "operation": text(data["operation"]),
        "root": text(data["root"]),
        "path": text(data["path"]),
        "reason": text(data["reason"]),
    }


def mismatch(value: object) -> VerificationMismatch:
    data = fields(value, "type root path expected observed")
    return VerificationMismatch(
        text(data["type"]),
        text(data["root"]),
        text(data["path"]),
        string(data["expected"]),
        string(data["observed"]),
    )


def verification(value: object) -> VerificationResult:
    data = fields(value, "complete mismatches obstacles")
    result = VerificationResult(
        boolean(data["complete"]),
        [mismatch(item) for item in json_list(data["mismatches"])],
        [parse_obstacle(item) for item in json_list(data["obstacles"])],
    )
    if result.complete and result.obstacles:
        raise ValueError("Complete verification cannot contain observation obstacles")
    return result


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
    prefix = relative.removesuffix(".json")
    for value in json_list(data["entries"]):
        entry = snapshot_entry(value, output, prefix)
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


def snapshot_entry(value: object, output: Path, prefix: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid snapshot entry")
    entry = cast(dict[str, object], value)
    if not {"root", "path", "kind"} <= entry.keys() or entry.keys() - {
        "root",
        "path",
        "kind",
        "content_file",
        "sha256",
        "listing_complete",
    }:
        raise ValueError("Invalid snapshot entry fields")
    root, path, kind = text(entry["root"]), text(entry["path"]), text(entry["kind"])
    if path != ".":
        relative_path(path)
    if root not in ({"subject"} if prefix == "expected" else {"project", "home"}):
        raise ValueError("Invalid snapshot root")
    if kind not in {"file", "directory", "unknown", "other"}:
        raise ValueError("Invalid snapshot entry kind")
    if "listing_complete" in entry:
        boolean(entry["listing_complete"])
    check_content_binding(entry, output, prefix)
    return entry


def check_content_binding(entry: dict[str, object], output: Path, prefix: str) -> None:
    root, path = entry["root"], entry["path"]
    if entry.get("content_file") is not None:
        binding = f"{prefix}/{path}" if root == "subject" else f"{prefix}/{root}/{path}"
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
