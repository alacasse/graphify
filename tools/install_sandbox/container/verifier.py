"""Compare retained observations against independent pre-operation sources."""

import json
import posixpath
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.case import InstallTestCase, destinations
from tools.install_sandbox.contracts.results import (
    FileAlterationPlan,
    ObservationObstacle,
    ReferenceRepairPlan,
    SkillBackupPlan,
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


def _check_markdown_alteration(
    case: InstallTestCase, before: bytes, altered: bytes, result: VerificationResult
) -> None:
    marker = case.spec.markdown_marker
    previous = _markdown_parts(before.decode("utf-8"), marker)
    planned = _markdown_parts(altered.decode("utf-8"), marker)
    if previous is None or planned is None or previous[1] == planned[1]:
        _mismatch(
            result,
            "invalid_preparation",
            "project",
            destinations(case)["markdown"],
            "one altered section with intact heading",
            "section not altered as required",
        )
    elif previous[0] != planned[0] or previous[2] != planned[2]:
        _mismatch(
            result,
            "user_content_lost",
            "project",
            destinations(case)["markdown"],
            "personal sections unchanged during preparation",
            "personal text changed",
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


def _json_equal(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _hook_entries(
    document: dict[str, object], event: str, matcher: str
) -> list[tuple[str, dict[str, object]]]:
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    groups = cast(dict[str, object], hooks).get(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"hooks.{event} must be a list")
    found: list[tuple[str, dict[str, object]]] = []
    for index, group in enumerate(cast(list[object], groups)):
        if not isinstance(group, dict):
            raise ValueError(f"hooks.{event}[{index}] must be an object")
        group = cast(dict[str, object], group)
        if group.get("matcher") == matcher:
            found.extend(_group_hooks(group, f"hooks.{event}[{index}].hooks"))
    return found


def _group_hooks(group: dict[str, object], path: str) -> list[tuple[str, dict[str, object]]]:
    values = group.get("hooks", [])
    if not isinstance(values, list):
        raise ValueError(f"{path} must be a list")
    found: list[tuple[str, dict[str, object]]] = []
    for index, value in enumerate(cast(list[object], values)):
        if not isinstance(value, dict):
            raise ValueError(f"{path}[{index}] must be an object")
        found.append((f"{path}[{index}]", cast(dict[str, object], value)))
    return found


def _hook_positions(
    document: dict[str, object],
    event: str,
    matcher: str,
    content: dict[str, object],
    *,
    exact: bool,
) -> list[str]:
    return [
        path
        for path, hook in _hook_entries(document, event, matcher)
        if (
            _json_equal(hook, content)
            if exact
            else all(
                key in hook and _json_equal(hook[key], value) for key, value in content.items()
            )
        )
    ]


def _hook_count(
    path: str,
    context: tuple[str, str, dict[str, object]],
    count: int,
    installed: dict[str, object],
    result: VerificationResult,
    *,
    personal: bool = False,
) -> None:
    event, matcher, content = context
    description = {"event": event, "matcher": matcher, "content": content, "count": count}
    try:
        positions = _hook_positions(installed, event, matcher, content, exact=personal)
    except ValueError as error:
        _mismatch(
            result,
            "invalid_json_hooks",
            "project",
            path,
            json.dumps(description, sort_keys=True),
            str(error),
        )
        return
    if len(positions) != count:
        _mismatch(
            result,
            "personal_hook_count" if personal else "hook_count",
            "project",
            path,
            json.dumps(description, sort_keys=True),
            json.dumps({"count": len(positions), "positions": positions}, sort_keys=True),
        )


def _personal_hook_contexts(
    initial: dict[str, object],
) -> list[tuple[str, str, dict[str, object]]]:
    # These are known case witnesses, never hooks inferred from installed output.
    contexts: dict[tuple[str, str, str], tuple[str, str, dict[str, object]]] = {}
    hooks = cast(dict[str, list[dict[str, object]]], initial.get("hooks", {}))
    for event, groups in hooks.items():
        for group in groups:
            matcher = cast(str, group["matcher"])
            for _, content in _group_hooks(group, f"hooks.{event}"):
                key = (event, matcher, json.dumps(content, sort_keys=True))
                contexts[key] = (event, matcher, content)
    return list(contexts.values())


def _json_hooks(
    case: InstallTestCase, installed: dict[str, object], result: VerificationResult
) -> None:
    path = destinations(case)["json"]
    for hook in case.spec.json_hooks:
        _hook_count(path, (hook.event, hook.matcher, hook.content), 1, installed, result)
    content = next(
        f["content"] for f in case.initial_files if f["root"] == "project" and f["path"] == path
    )
    initial = _read_json(content.encode("utf-8"))
    for context in _personal_hook_contexts(initial):
        count = len(_hook_positions(initial, *context, exact=True))
        _hook_count(path, context, count, installed, result, personal=True)


def _json_instructions(
    case: InstallTestCase,
    initial: dict[str, object],
    installed: dict[str, object],
    result: VerificationResult,
) -> bool:
    dest = destinations(case)
    path = dest["json"]
    value = posixpath.relpath(dest["skill"], posixpath.dirname(path))
    items = installed.get(case.spec.json_list)
    if not isinstance(items, list):
        _mismatch(result, "json_list", "project", path, "instruction list", "list unavailable")
        return False
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
    return True


def _without_hooks(document: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in document.items() if key != "hooks"}


def _json(case: InstallTestCase, before: bytes, after: bytes, result: VerificationResult) -> None:
    path = destinations(case)["json"]
    try:
        initial, installed = _read_json(before), _read_json(after)
    except (ValueError, UnicodeDecodeError):
        _mismatch(result, "invalid_json", "project", path, "valid JSON object", "invalid JSON")
        return
    _json_hooks(case, installed, result)
    if not _json_instructions(case, initial, installed, result):
        return
    if not _json_equal(_without_hooks(initial), _without_hooks(installed)):
        _mismatch(
            result,
            "user_content_lost",
            "project",
            path,
            "user JSON values and list order preserved",
            "user values changed",
        )


def _json_preparation(
    expected: bytes,
    observed: bytes,
    previous: bytes | None,
    path: str,
    result: VerificationResult,
) -> None:
    try:
        expected_json, observed_json = _read_json(expected), _read_json(observed)
        if not _json_equal(_without_hooks(expected_json), _without_hooks(observed_json)):
            _mismatch(
                result,
                "invalid_preparation",
                "project",
                path,
                "personal JSON with only the skill entry removed",
                "different JSON",
            )
        if previous is not None:
            installed = _read_json(previous)
            # Keep absence distinct from a newly introduced empty branch.
            left = {k: v for k, v in installed.items() if k == "hooks"}
            right = {k: v for k, v in observed_json.items() if k == "hooks"}
            if not _json_equal(left, right):
                _mismatch(
                    result,
                    "invalid_preparation",
                    "project",
                    path,
                    "hooks unchanged during preparation",
                    "different hooks",
                )
    except (ValueError, UnicodeError):
        _mismatch(result, "invalid_json", "project", path, "valid JSON object", "invalid JSON")


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
    skill_backup: bytes | None = None,
) -> None:
    allowed = _allowed(case, expected)
    if skill_backup is not None:
        allowed.add(destinations(case)["skill"] + ".bak")
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
    if case.name not in {
        "reinstall",
        "repair-references",
        "repair-skill",
        "preserve-skill-backup",
        "repair-markdown-section",
        "repair-json-entry",
    }:
        return
    dest = destinations(case)
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
        *,
        skill_backup: bytes | None = None,
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
        _preservation(case, expected, before, after, result, skill_backup)
        if skill_backup is not None:
            _compare_bytes(after, dest["skill"] + ".bak", skill_backup, result)
        elif case.name != "first-install":
            _require_absent(after, dest["skill"] + ".bak", result)
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

    def verify_skill_repair(
        self,
        plan: FileAlterationPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Require exactly the skill alteration and no backup or other change."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        _compare_bytes(degraded, plan["altered_path"], content, result)
        _require_absent(degraded, plan["altered_path"] + ".bak", result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, path in sorted(keys):
            if (root, path) != ("project", plan["altered_path"]):
                _preserved_entry(installed, degraded, root, path, result)
        result.complete = not result.obstacles
        return result

    def verify_markdown_repair(
        self,
        case: InstallTestCase,
        plan: FileAlterationPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Require the exact shared document witness and no other changed entry."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        _compare_bytes(degraded, plan["altered_path"], content, result)
        previous = installed.contents.get(("project", plan["altered_path"]))
        if previous is not None:
            _check_markdown_alteration(case, previous, content, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, path in sorted(keys):
            if (root, path) != ("project", plan["altered_path"]):
                _preserved_entry(installed, degraded, root, path, result)
        result.complete = not result.obstacles
        return result

    def verify_json_repair(
        self,
        case: InstallTestCase,
        plan: FileAlterationPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Compare personal JSON against the case and preserve every other entry."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        path = plan["altered_path"]
        observed = _file(degraded, path, result)
        previous = _file(installed, path, result)
        if observed is not None:
            _json_preparation(content, observed, previous, path, result)
        if previous is not None:
            _json(case, content, previous, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, entry_path in sorted(keys):
            if (root, entry_path) != ("project", path):
                _preserved_entry(installed, degraded, root, entry_path, result)
        result.complete = not result.obstacles
        return result

    def verify_skill_backup(
        self,
        plan: SkillBackupPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        prepared: FilesystemSnapshot,
    ) -> VerificationResult:
        """Require exactly the new backup, with every existing entry unchanged."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, prepared) for o in s.obstacles]
        )
        _require_absent(installed, plan["backup_path"], result)
        _compare_bytes(prepared, plan["backup_path"], content, result)
        keys = {(e["root"], e["path"]) for s in (installed, prepared) for e in s.entries}
        for root, path in sorted(keys):
            if (root, path) != ("project", plan["backup_path"]):
                _preserved_entry(installed, prepared, root, path, result)
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
