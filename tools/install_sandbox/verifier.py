"""Compare retained observations against independent pre-operation sources."""

import json
import posixpath
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.environment import destinations
from tools.install_sandbox.results import (
    FilesystemSnapshot,
    ObservationObstacle,
    ReferenceRepairPlan,
    SnapshotEntry,
    VerificationMismatch,
    VerificationResult,
)


def _mismatch(
    result: VerificationResult, kind: str, root: str, path: str, expected: str, observed: str
) -> None:
    result.mismatches.append(VerificationMismatch(kind, root, path, expected, observed))


def _file(snapshot: FilesystemSnapshot, path: str, result: VerificationResult) -> bytes | None:
    entry = snapshot.entry("project", path)
    if entry is None:
        if snapshot.absent("project", path):
            _mismatch(result, "missing_file", "project", path, "file present", "file absent")
    elif entry["kind"] not in {"file", "unknown"}:
        _mismatch(result, "entry_kind", "project", path, "file", entry["kind"])
    return snapshot.contents.get(("project", path))


def _compare_bytes(
    snapshot: FilesystemSnapshot, path: str, expected: bytes, result: VerificationResult
) -> None:
    observed = _file(snapshot, path, result)
    if observed is not None and observed != expected:
        _mismatch(
            result,
            "content_mismatch",
            "project",
            path,
            "bytes identical to retained source",
            "different bytes",
        )


def _expected_file(
    expected: FilesystemSnapshot, path: str, result: VerificationResult
) -> bytes | None:
    content = expected.contents.get(("subject", path))
    if content is None and not any(o["path"] == path for o in expected.obstacles):
        result.obstacles.append(
            {
                "operation": "read_expected",
                "root": "subject",
                "path": path,
                "reason": "Expected source file content unavailable",
            }
        )
    return content


def _references(
    case: InstallTestCase,
    expected: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    source = case.spec.references_source
    destination = destinations(case)["references"]
    entry = expected.entry("subject", source)
    if entry is None or entry["kind"] != "directory":
        result.obstacles.append(
            {
                "operation": "list_directory",
                "root": "subject",
                "path": source,
                "reason": "Expected references directory unavailable",
            }
        )
        return
    _reference_files(expected, after, source, destination, result)
    for observed in after.entries:
        path = observed["path"]
        if observed["root"] != "project" or not path.startswith(destination + "/"):
            continue
        source_path = source + path[len(destination) :]
        if expected.absent("subject", source_path):
            _mismatch(
                result,
                "unexpected_reference",
                "project",
                path,
                "no additional reference entry",
                observed["kind"],
            )


def _reference_files(
    expected: FilesystemSnapshot,
    after: FilesystemSnapshot,
    source: str,
    destination: str,
    result: VerificationResult,
) -> None:
    for entry in expected.entries:
        path = entry["path"]
        if path != source and not path.startswith(source + "/"):
            continue
        target = destination + path[len(source) :]
        if entry["kind"] == "directory":
            observed = after.entry("project", target)
            if observed is not None and observed["kind"] not in {"directory", "unknown"}:
                _mismatch(result, "entry_kind", "project", target, "directory", observed["kind"])
            elif after.absent("project", target):
                _mismatch(
                    result,
                    "missing_directory",
                    "project",
                    target,
                    "directory present",
                    "directory absent",
                )
        elif entry["kind"] == "file":
            content = _expected_file(expected, path, result)
            if content is not None:
                _compare_bytes(after, target, content, result)


def _markdown_parts(text: str, marker: str) -> tuple[str, str, str] | None:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == marker]
    if len(starts) != 1:
        return None
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(("## ", "# "))), len(lines)
    )
    return "".join(lines[:start]), "".join(lines[start:end]), "".join(lines[end:])


def _user_markdown_preserved(before: str, prefix: str, suffix: str) -> bool:
    prefix, suffix = prefix.rstrip("\n"), suffix.lstrip("\n")
    if not before.startswith(prefix) or not before.endswith(suffix):
        return False
    end = len(before) - len(suffix) if suffix else len(before)
    return end >= len(prefix) and not before[len(prefix) : end].strip("\n")


def _markdown_preserved(before: str, prefix: str, suffix: str, marker: str) -> bool:
    parts = _markdown_parts(before, marker)
    if parts is None:
        return _user_markdown_preserved(before, prefix, suffix)
    return parts[0].rstrip("\n") == prefix.rstrip("\n") and parts[2].lstrip("\n") == suffix.lstrip(
        "\n"
    )


def _markdown(
    case: InstallTestCase, expected: bytes, before: bytes, after: bytes, result: VerificationResult
) -> None:
    path = destinations(case)["markdown"]
    try:
        source, initial, installed = (b.decode("utf-8") for b in (expected, before, after))
    except UnicodeDecodeError:
        _mismatch(result, "invalid_markdown", "project", path, "UTF-8 text", "invalid UTF-8")
        return
    parts = _markdown_parts(installed, case.spec.markdown_marker)
    if parts is None:
        _mismatch(
            result,
            "section_count",
            "project",
            path,
            "one Graphify section",
            "zero or multiple Graphify sections",
        )
        return
    prefix, section, suffix = parts
    if section.rstrip("\n") != source.rstrip("\n"):
        _mismatch(
            result,
            "content_mismatch",
            "project",
            path,
            "retained Markdown section",
            "different section content",
        )
    if not _markdown_preserved(initial, prefix, suffix, case.spec.markdown_marker):
        _mismatch(
            result,
            "user_content_lost",
            "project",
            path,
            "user text and section order preserved",
            "user content changed",
        )


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Duplicate JSON key")
        data[key] = value
    return data


def _reject_constant(value: str) -> object:
    raise ValueError(f"Invalid JSON constant: {value}")


def _read_json(content: bytes) -> dict[str, object]:
    value: object = json.loads(
        content.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_reject_constant
    )
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return cast(dict[str, object], value)


def _json(case: InstallTestCase, before: bytes, after: bytes, result: VerificationResult) -> None:
    dest = destinations(case)
    path = dest["json"]
    try:
        initial, installed = _read_json(before), _read_json(after)
    except (ValueError, UnicodeDecodeError):
        _mismatch(result, "invalid_json", "project", path, "valid JSON object", "invalid JSON")
        return
    value = posixpath.relpath(dest["skill"], posixpath.dirname(path))
    items = installed.get(case.spec.json_list)
    if not isinstance(items, list):
        _mismatch(result, "json_list", "project", path, "instruction list", "list unavailable")
        return
    items = cast(list[object], items)
    if items.count(value) != 1:
        _mismatch(
            result,
            "json_entry_count",
            "project",
            path,
            "one skill instruction",
            f"{items.count(value)} skill instructions",
        )
    installed[case.spec.json_list] = [item for item in items if item != value]
    initial_items = initial.get(case.spec.json_list)
    if isinstance(initial_items, list):
        initial[case.spec.json_list] = [
            item for item in cast(list[object], initial_items) if item != value
        ]
    if json.dumps(initial, sort_keys=True) != json.dumps(installed, sort_keys=True):
        _mismatch(
            result,
            "user_content_lost",
            "project",
            path,
            "user JSON values and list order preserved",
            "user values changed",
        )


def _allowed(case: InstallTestCase, expected: FilesystemSnapshot) -> set[str]:
    dest = destinations(case)
    paths = set(dest.values())
    source = case.spec.references_source
    paths.update(
        dest["references"] + e["path"][len(source) :]
        for e in expected.entries
        if e["path"].startswith(source + "/")
    )
    paths.update(str(parent) for path in tuple(paths) for parent in PurePosixPath(path).parents)
    return paths


def _same_file(
    before: FilesystemSnapshot, after: FilesystemSnapshot, left: SnapshotEntry, right: SnapshotEntry
) -> bool | None:
    key = (left["root"], left["path"])
    if key in before.contents and key in after.contents:
        return before.contents[key] == after.contents[key]
    if left.get("sha256") is not None and right.get("sha256") is not None:
        return left.get("sha256") == right.get("sha256")
    return None


def _preservation(
    case: InstallTestCase,
    expected: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    allowed = _allowed(case, expected)
    keys = {(e["root"], e["path"]) for s in (before, after) for e in s.entries}
    for root, path in sorted(keys):
        # An incomplete source inventory cannot establish unauthorized membership.
        references = destinations(case)["references"]
        source_path = case.spec.references_source + path[len(references) :]
        if (
            root == "project"
            and path.startswith(references + "/")
            and not expected.absent("subject", source_path)
        ):
            continue
        left, right = before.entry(root, path), after.entry(root, path)
        if root == "project" and path in allowed:
            # Only creation of required directories is authorized, never their removal/type change.
            if left is None or (
                left["kind"] == "directory" and right is not None and right["kind"] == "directory"
            ):
                continue
            if left["kind"] != "directory" and right is not None and right["kind"] != "directory":
                continue
        _preserved_entry(before, after, root, path, result)


def _preserved_entry(
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    root: str,
    path: str,
    result: VerificationResult,
) -> None:
    left, right = before.entry(root, path), after.entry(root, path)
    changed = False
    if left is None:
        changed = before.absent(root, path)
    elif right is None:
        changed = after.absent(root, path)
    elif "unknown" in (left["kind"], right["kind"]):
        return
    elif left["kind"] != right["kind"]:
        changed = True
    elif left["kind"] == "file":
        changed = _same_file(before, after, left, right) is False
    if changed:
        _mismatch(
            result,
            "unexpected_change",
            root,
            path,
            "entry preserved",
            "entry added, removed or changed",
        )


def _require_absent(snapshot: FilesystemSnapshot, path: str, result: VerificationResult) -> None:
    entry = snapshot.entry("project", path)
    if entry is not None:
        _mismatch(result, "unexpected_entry", "project", path, "absent", entry["kind"])
    elif not snapshot.absent("project", path):
        result.obstacles.append(
            {
                "operation": "verify_absence",
                "root": "project",
                "path": path,
                "reason": "Absence could not be established",
            }
        )


def _reinstall_stability(
    case: InstallTestCase,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    if case.name not in {"reinstall", "repair-references"}:
        return
    dest = destinations(case)
    _require_absent(after, dest["skill"] + ".bak", result)
    key = ("project", dest["version"])
    previous, current = before.contents.get(key), after.contents.get(key)
    if previous is not None and current is not None and previous != current:
        _mismatch(
            result,
            "version_changed",
            *key,
            "same bytes as first installation",
            "different version bytes",
        )
    for snapshot in (before, after):
        entry = snapshot.entry(*key)
        if entry is not None and entry["kind"] == "file" and key not in snapshot.contents:
            result.obstacles.append(
                {
                    "operation": "read_file",
                    "root": key[0],
                    "path": key[1],
                    "reason": "Version content unavailable",
                }
            )


class InstallVerifier:
    def verify(
        self,
        case: InstallTestCase,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        after: FilesystemSnapshot,
    ) -> VerificationResult:
        result = VerificationResult(
            obstacles=[
                ObservationObstacle(**o)
                for snapshot in (expected, before, after)
                for o in snapshot.obstacles
            ]
        )
        dest = destinations(case)
        skill = _expected_file(expected, case.spec.skill_source, result)
        if skill is not None:
            _compare_bytes(after, dest["skill"], skill, result)
        _references(case, expected, after, result)
        _file(after, dest["version"], result)
        self._shared_files(case, expected, before, after, result)
        _preservation(case, expected, before, after, result)
        _reinstall_stability(case, before, after, result)
        result.complete = not result.obstacles
        return result

    def verify_reference_repair(
        self,
        plan: ReferenceRepairPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Check exactly two intended changes, preserving every other observed entry."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        _require_absent(degraded, plan["deleted_path"], result)
        _compare_bytes(degraded, plan["altered_path"], content, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, path in sorted(keys):
            if root == "project" and path in (plan["deleted_path"], plan["altered_path"]):
                continue
            _preserved_entry(installed, degraded, root, path, result)
        result.complete = not result.obstacles
        return result

    def verify_initial(
        self, case: InstallTestCase, expected: FilesystemSnapshot, before: FilesystemSnapshot
    ) -> VerificationResult:
        """Expose preparation readiness without inventing a case execution status."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (expected, before) for o in s.obstacles]
        )
        for initial in case.initial_files:
            key = (initial["root"], initial["path"])
            if before.contents.get(key) != initial["content"].encode("utf-8"):
                result.obstacles.append(
                    {
                        "operation": "verify_initial",
                        "root": key[0],
                        "path": key[1],
                        "reason": "Initial witness content unavailable or different from the case",
                    }
                )
        for source in (case.spec.skill_source, case.spec.markdown_source):
            _expected_file(expected, source, result)
        reference = expected.entry("subject", case.spec.references_source)
        if reference is None or reference["kind"] != "directory":
            result.obstacles.append(
                {
                    "operation": "verify_initial",
                    "root": "subject",
                    "path": case.spec.references_source,
                    "reason": "Expected references directory unavailable",
                }
            )
        dest = destinations(case)
        for path in (dest["skill"], dest["references"], dest["version"], dest["skill"] + ".bak"):
            _require_absent(before, path, result)
        result.complete = not result.obstacles
        return result

    def _shared_files(
        self,
        case: InstallTestCase,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        after: FilesystemSnapshot,
        result: VerificationResult,
    ) -> None:
        dest = destinations(case)
        source = _expected_file(expected, case.spec.markdown_source, result)
        for kind in ("markdown", "json"):
            path = dest[kind]
            initial = before.contents.get(("project", path))
            installed = _file(after, path, result)
            if initial is None or installed is None:
                continue
            if kind == "markdown" and source is not None:
                _markdown(case, source, initial, installed, result)
            elif kind == "json":
                _json(case, initial, installed, result)
