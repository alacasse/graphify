"""Compare retained observations against independent pre-operation sources."""

import json
import posixpath
from copy import deepcopy
from email.parser import BytesParser
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.case import (
    InstallTestCase,
    destination_roots,
    destinations,
    remove_json_hook,
    transform_json_hook,
)
from tools.install_sandbox.contracts.managed_json import registry, sidecars
from tools.install_sandbox.contracts.results import (
    AlteredReferencePlan,
    FileAlterationPlan,
    MissingReferencePlan,
    ObservationObstacle,
    ReferenceRepairPlan,
    SkillBackupPlan,
    SnapshotEntry,
    VerificationMismatch,
    VerificationResult,
)


def mismatch(
    result: VerificationResult, kind: str, root: str, path: str, expected: str, observed: str
) -> None:
    result.mismatches.append(VerificationMismatch(kind, root, path, expected, observed))


def file(
    snapshot: FilesystemSnapshot,
    path: str,
    result: VerificationResult,
    root: str = "project",
    *,
    require_content: bool = True,
) -> bytes | None:
    entry = snapshot.entry(root, path)
    if entry is None:
        if snapshot.absent(root, path):
            mismatch(result, "missing_file", root, path, "file present", "file absent")
    elif entry["kind"] not in {"file", "unknown"}:
        mismatch(result, "entry_kind", root, path, "file", entry["kind"])
    content = snapshot.contents.get((root, path))
    if require_content and content is None and entry is not None and entry["kind"] == "file":
        result.obstacles.append(
            {
                "operation": "read_file",
                "root": root,
                "path": path,
                "reason": "File content unavailable",
            }
        )
    return content


def compare_bytes(
    snapshot: FilesystemSnapshot,
    path: str,
    expected: bytes,
    result: VerificationResult,
    root: str = "project",
) -> None:
    observed = file(snapshot, path, result, root)
    if observed is not None and observed != expected:
        mismatch(
            result,
            "content_mismatch",
            root,
            path,
            "bytes identical to retained source",
            "different bytes",
        )


def expected_file(
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
    root = destination_roots(case)["references"]
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
    reference_files(expected, after, source, destination, result, root)
    for observed in after.entries:
        path = observed["path"]
        if observed["root"] != root or not path.startswith(destination + "/"):
            continue
        source_path = source + path[len(destination) :]
        if expected.absent("subject", source_path):
            mismatch(
                result,
                "unexpected_reference",
                root,
                path,
                "no additional reference entry",
                observed["kind"],
            )


def reference_files(
    expected: FilesystemSnapshot,
    after: FilesystemSnapshot,
    source: str,
    destination: str,
    result: VerificationResult,
    root: str,
) -> None:
    for entry in expected.entries:
        path = entry["path"]
        if path != source and not path.startswith(source + "/"):
            continue
        target = destination + path[len(source) :]
        if entry["kind"] == "directory":
            observed = after.entry(root, target)
            if observed is not None and observed["kind"] not in {"directory", "unknown"}:
                mismatch(result, "entry_kind", root, target, "directory", observed["kind"])
            elif after.absent(root, target):
                mismatch(
                    result,
                    "missing_directory",
                    root,
                    target,
                    "directory present",
                    "directory absent",
                )
        elif entry["kind"] == "file":
            content = expected_file(expected, path, result)
            if content is not None:
                compare_bytes(after, target, content, result, root)


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
    case: InstallTestCase,
    expected: bytes,
    before: bytes,
    after: bytes,
    result: VerificationResult,
    allow_markdown_relocation: bool = False,
) -> None:
    verify_markdown_section(
        expected,
        before,
        after,
        result,
        root=destination_roots(case)["markdown"],
        path=destinations(case)["markdown"],
        marker=case.spec.markdown_marker,
        allow_markdown_relocation=(
            allow_markdown_relocation and case.name == "repair-missing-markdown-section"
        ),
    )


def verify_markdown_section(
    expected: bytes,
    before: bytes,
    after: bytes,
    result: VerificationResult,
    *,
    root: str,
    path: str,
    marker: str,
    allow_markdown_relocation: bool = False,
) -> None:
    """Check a unique source section and preserve surrounding personal text."""
    try:
        source, initial, installed = (b.decode("utf-8") for b in (expected, before, after))
    except UnicodeDecodeError:
        mismatch(
            result,
            "invalid_markdown",
            root,
            path,
            "UTF-8 text",
            "invalid UTF-8",
        )
        return
    parts = _markdown_parts(installed, marker)
    if parts is None:
        mismatch(
            result,
            "section_count",
            root,
            path,
            "one Graphify section",
            "zero or multiple Graphify sections",
        )
        return
    prefix, section, suffix = parts
    if section.rstrip("\n") != source.rstrip("\n"):
        mismatch(
            result,
            "content_mismatch",
            root,
            path,
            "retained Markdown section",
            "different section content",
        )
    preserved = _markdown_preserved(initial, prefix, suffix, marker)
    if allow_markdown_relocation:
        original = _markdown_parts(initial, marker)
        if original is not None:
            preserved = _personal_markdown(original[0], original[2]) == _personal_markdown(
                prefix, suffix
            )
    if not preserved:
        mismatch(
            result,
            "user_content_lost",
            root,
            path,
            "user text and section order preserved",
            "user content changed",
        )


def _personal_markdown(prefix: str, suffix: str) -> str:
    """Join personal text while allowing only the section separator newlines."""
    return "\n\n".join(part for part in (prefix.strip("\n"), suffix.strip("\n")) if part)


def _check_markdown_alteration(
    case: InstallTestCase, before: bytes, altered: bytes, result: VerificationResult
) -> None:
    marker = case.spec.markdown_marker
    previous = _markdown_parts(before.decode("utf-8"), marker)
    planned = _markdown_parts(altered.decode("utf-8"), marker)
    if case.name == "repair-missing-markdown-section":
        if previous is None or previous[0] + previous[2] != altered.decode("utf-8"):
            mismatch(
                result,
                "invalid_preparation",
                destination_roots(case)["markdown"],
                destinations(case)["markdown"],
                "only the entire Graphify section removed",
                "section removal differs from the installed personal text",
            )
        return
    if previous is None or planned is None or previous[1] == planned[1]:
        mismatch(
            result,
            "invalid_preparation",
            destination_roots(case)["markdown"],
            destinations(case)["markdown"],
            "one altered section with intact heading",
            "section not altered as required",
        )
    elif previous[0] != planned[0] or previous[2] != planned[2]:
        mismatch(
            result,
            "user_content_lost",
            destination_roots(case)["markdown"],
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


def read_json(content: bytes) -> dict[str, object]:
    value: object = json.loads(
        content.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_reject_constant
    )
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return cast(dict[str, object], value)


def json_equal(left: object, right: object) -> bool:
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
            found.extend(group_hooks(group, f"hooks.{event}[{index}].hooks"))
    return found


def group_hooks(group: dict[str, object], path: str) -> list[tuple[str, dict[str, object]]]:
    values = group.get("hooks", [])
    if not isinstance(values, list):
        raise ValueError(f"{path} must be a list")
    found: list[tuple[str, dict[str, object]]] = []
    for index, value in enumerate(cast(list[object], values)):
        if not isinstance(value, dict):
            raise ValueError(f"{path}[{index}] must be an object")
        found.append((f"{path}[{index}]", cast(dict[str, object], value)))
    return found


def hook_positions(
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
            json_equal(hook, content)
            if exact
            else all(key in hook and json_equal(hook[key], value) for key, value in content.items())
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
    root: str = "project",
) -> None:
    event, matcher, content = context
    description = {"event": event, "matcher": matcher, "content": content, "count": count}
    try:
        positions = hook_positions(installed, event, matcher, content, exact=personal)
    except ValueError as error:
        mismatch(
            result,
            "invalid_json_hooks",
            root,
            path,
            json.dumps(description, sort_keys=True),
            str(error),
        )
        return
    if len(positions) != count:
        mismatch(
            result,
            "personal_hook_count" if personal else "hook_count",
            root,
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
            matcher = cast(str, group.get("matcher", ""))
            for _, content in group_hooks(group, f"hooks.{event}"):
                key = (event, matcher, json.dumps(content, sort_keys=True))
                contexts[key] = (event, matcher, content)
    return list(contexts.values())


def _json_hooks(
    case: InstallTestCase, installed: dict[str, object], result: VerificationResult
) -> None:
    path = destinations(case)["json"]
    for hook in case.spec.json_hooks:
        _hook_count(
            path,
            (hook.event, hook.matcher, hook.content),
            1,
            installed,
            result,
            root=destination_roots(case)["json"],
        )


def _json_instructions(
    case: InstallTestCase,
    initial: dict[str, object],
    installed: dict[str, object],
    result: VerificationResult,
) -> bool:
    if case.spec.json_list is None:
        return True
    dest = destinations(case)
    path = dest["json"]
    value = posixpath.relpath(dest["skill"], posixpath.dirname(path))
    items = installed.get(case.spec.json_list)
    if not isinstance(items, list):
        mismatch(
            result,
            "json_list",
            destination_roots(case)["json"],
            path,
            "instruction list",
            "list unavailable",
        )
        return False
    items = cast(list[object], items)
    if items.count(value) != 1:
        mismatch(
            result,
            "json_entry_count",
            destination_roots(case)["json"],
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


def _personal_groups(case: InstallTestCase, event: str, groups: list[object]) -> list[object]:
    """Preserve personal groups while removing independently declared managed hooks."""
    personal_groups: list[object] = []
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Hook groups must be objects")
        group = cast(dict[str, object], raw)
        entries = group_hooks(group, f"hooks.{event}")
        personal = [
            content
            for _, content in entries
            if not any(
                hook.event == event
                and hook.matcher == group.get("matcher")
                and (
                    json_equal(content, hook.content)
                    if case.spec.json_hook_management == "registry"
                    else all(
                        key in content and json_equal(content[key], value)
                        for key, value in hook.content.items()
                    )
                )
                for hook in case.spec.json_hooks
            )
        ]
        removed = len(personal) != len(entries)
        if removed and not personal and set(group) == {"matcher", "hooks"}:
            continue
        personal_groups.append({**group, "hooks": personal} if removed else group)
    return personal_groups


def _personal_json(case: InstallTestCase, document: dict[str, object]) -> dict[str, object]:
    """Remove only independently declared managed hooks, retaining personal context/order."""
    result = dict(document)
    hooks = document.get("hooks")
    if hooks is None:
        return result
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    events: dict[str, object] = {}
    for event, groups in cast(dict[str, object], hooks).items():
        if not isinstance(groups, list):
            raise ValueError("Hook events must contain group lists")
        personal_groups = _personal_groups(case, event, cast(list[object], groups))
        if personal_groups or not groups:
            events[event] = personal_groups
    if events or not hooks:
        result["hooks"] = events
    else:
        result.pop("hooks", None)
    return result


def _initial_json(case: InstallTestCase) -> dict[str, object]:
    path = destinations(case)["json"]
    root = destination_roots(case)["json"]
    content = next(
        f["content"] for f in case.initial_files if f["root"] == root and f["path"] == path
    )
    return read_json(content.encode("utf-8"))


def _personal_values(
    case: InstallTestCase, initial: dict[str, object], installed: dict[str, object]
) -> bool:
    if not json_equal(_without_hooks(initial), _without_hooks(installed)):
        return False
    if case.spec.json_hook_management == "registry":
        return True  # Legacy registry contract permits regrouping personal hooks.
    original = _personal_json(case, _initial_json(case))
    current = _personal_json(case, installed)
    if json_equal(
        {key: value for key, value in original.items() if key == "hooks"},
        {key: value for key, value in current.items() if key == "hooks"},
    ):
        return True
    # A repair may move the search hook out of its previously observed bare group.
    return case.name in {"repair-altered-json-hook", "repair-duplicate-json-hook"} and (
        _same_hook_json(case, initial, installed)
    )


def _json(case: InstallTestCase, before: bytes, after: bytes, result: VerificationResult) -> None:
    path = destinations(case)["json"]
    root = destination_roots(case)["json"]
    try:
        initial, installed = read_json(before), read_json(after)
        _json_hooks(case, installed, result)
        personal_initial = _initial_json(case)
        for context in _personal_hook_contexts(personal_initial):
            count = len(hook_positions(personal_initial, *context, exact=True))
            _hook_count(path, context, count, installed, result, personal=True, root=root)
        if not _json_instructions(case, initial, installed, result):
            return
        if not _personal_values(case, initial, installed):
            mismatch(
                result,
                "user_content_lost",
                root,
                path,
                "personal JSON, hook contexts, counts and array order preserved",
                "personal JSON changed",
            )
    except (ValueError, UnicodeDecodeError):
        mismatch(result, "invalid_json", root, path, "valid JSON object and hooks", "invalid JSON")


def _json_preparation(
    expected: bytes,
    observed: bytes,
    previous: bytes | None,
    path: str,
    result: VerificationResult,
) -> None:
    try:
        expected_json, observed_json = read_json(expected), read_json(observed)
        if not json_equal(_without_hooks(expected_json), _without_hooks(observed_json)):
            mismatch(
                result,
                "invalid_preparation",
                "project",
                path,
                "personal JSON with only the skill entry removed",
                "different JSON",
            )
        if previous is not None:
            installed = read_json(previous)
            # Keep absence distinct from a newly introduced empty branch.
            left = {k: v for k, v in installed.items() if k == "hooks"}
            right = {k: v for k, v in observed_json.items() if k == "hooks"}
            if not json_equal(left, right):
                mismatch(
                    result,
                    "invalid_preparation",
                    "project",
                    path,
                    "hooks unchanged during preparation",
                    "different hooks",
                )
    except (ValueError, UnicodeError):
        mismatch(result, "invalid_json", "project", path, "valid JSON object", "invalid JSON")


def _allowed(case: InstallTestCase, expected: FilesystemSnapshot) -> set[tuple[str, str]]:
    dest = destinations(case)
    roots = destination_roots(case)
    paths = {(roots[kind], path) for kind, path in dest.items()}
    if case.spec.json_hook_management == "registry":
        paths.update((roots["json"], path) for path in sidecars(case).values())
    if case.spec.json_backup is not None:
        paths.add((roots["json"], dest["json"] + case.spec.json_backup))
    source = case.spec.references_source
    paths.update(
        (roots["references"], dest["references"] + e["path"][len(source) :])
        for e in expected.entries
        if e["root"] == "subject" and e["path"].startswith(source + "/")
    )
    paths.update(
        (root, str(parent)) for root, path in tuple(paths) for parent in PurePosixPath(path).parents
    )
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
        allowed.add((destination_roots(case)["skill"], destinations(case)["skill"] + ".bak"))
    keys = {(e["root"], e["path"]) for s in (before, after) for e in s.entries}
    for root, path in sorted(keys):
        # An incomplete source inventory cannot establish unauthorized membership.
        references = destinations(case)["references"]
        source_path = case.spec.references_source + path[len(references) :]
        if (
            root == destination_roots(case)["references"]
            and path.startswith(references + "/")
            and not expected.absent("subject", source_path)
        ):
            continue
        left, right = before.entry(root, path), after.entry(root, path)
        if root == "home" and _lock_creation(expected.skill_lock, before, after, path):
            continue
        if (root, path) in allowed:
            # Only creation of required directories is authorized, never their removal/type change.
            if left is None or (
                left["kind"] == "directory" and right is not None and right["kind"] == "directory"
            ):
                continue
            if left["kind"] != "directory" and right is not None and right["kind"] != "directory":
                continue
        preserved_entry(before, after, root, path, result)


def preserved_entry(
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
        mismatch(
            result,
            "unexpected_change",
            root,
            path,
            "entry preserved",
            "entry added, removed or changed",
        )


def require_absent(
    snapshot: FilesystemSnapshot, path: str, result: VerificationResult, root: str = "project"
) -> None:
    entry = snapshot.entry(root, path)
    if entry is not None:
        mismatch(result, "unexpected_entry", root, path, "absent", entry["kind"])
    elif not snapshot.absent(root, path):
        result.obstacles.append(
            {
                "operation": "verify_absence",
                "root": root,
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
        "repair-missing-reference",
        "repair-altered-reference",
        "repair-skill",
        "preserve-skill-backup",
        "repair-markdown-section",
        "repair-missing-markdown-section",
        "repair-json-entry",
        "repair-missing-json-hook",
        "repair-altered-json-hook",
        "repair-duplicate-json-hook",
    }:
        return
    dest = destinations(case)
    key = (destination_roots(case)["version"], dest["version"])
    previous, current = before.contents.get(key), after.contents.get(key)
    if previous is not None and current is not None and previous != current:
        mismatch(
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


def _json_backup(
    case: InstallTestCase,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    if case.spec.json_backup is None:
        return
    root = destination_roots(case)["json"]
    path = destinations(case)["json"]
    backup = path + case.spec.json_backup
    source = path
    if (
        case.name
        in {
            "reinstall",
            "repair-missing-reference",
            "repair-altered-reference",
            "repair-skill",
            "preserve-skill-backup",
            "repair-markdown-section",
            "repair-missing-markdown-section",
            "repair-missing-json-hook",
            "repair-altered-json-hook",
            "repair-duplicate-json-hook",
        }
        and case.spec.json_hook_management == "none"
        and before.entry(root, backup) is not None
    ):
        source = backup
        original = file(before, path, result, root)
        if original is not None:
            if case.name in {
                "repair-missing-json-hook",
                "repair-altered-json-hook",
                "repair-duplicate-json-hook",
            }:
                _restored_hook_json(
                    case, original, file(after, path, result, root), root, path, result
                )
            else:
                compare_bytes(after, path, original, result, root)
    original = file(before, source, result, root)
    if original is not None:
        compare_bytes(after, backup, original, result, root)


def _lock_creation(
    lock: str | None, before: FilesystemSnapshot, after: FilesystemSnapshot, path: str
) -> bool:
    if lock is None or not before.absent("home", path):
        return False
    if path == lock:
        return True
    entry = after.entry("home", path)
    return (
        path in {str(p) for p in PurePosixPath(lock).parents}
        and entry is not None
        and entry["kind"] == "directory"
    )


def skill_lock(
    path: str | None,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    if path is None:
        return
    entry = after.entry("home", path)
    if entry is None:
        if after.absent("home", path):
            mismatch(result, "missing_file", "home", path, "persistent lock", "absent")
        return
    if entry["kind"] != "file":
        mismatch(result, "entry_kind", "home", path, "ordinary file", entry["kind"])
        return
    key = ("home", path)
    previous = b"" if before.absent(*key) else before.contents.get(key)
    current = after.contents.get(key)
    if previous is None or current is None:
        result.obstacles.append(
            {
                "operation": "read_lock",
                "root": "home",
                "path": path,
                "reason": "Persistent lock bytes unavailable",
            }
        )
    elif previous != current:
        mismatch(
            result,
            "content_mismatch",
            "home",
            path,
            "preserved bytes or empty new lock",
            "different bytes",
        )


def _version(
    case: InstallTestCase,
    expected: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    path = destinations(case)["version"]
    root = destination_roots(case)["version"]
    observed = file(after, path, result, root, require_content=case.spec.version_source is not None)
    if case.spec.version_source is None:
        return
    source = expected_file(expected, case.spec.version_source, result)
    if source is None:
        return
    try:
        metadata = BytesParser().parsebytes(source)
        versions = metadata.get_all("Version", [])
        if len(versions) != 1 or not versions[0].strip():
            raise ValueError("Expected one non-empty Core Metadata Version header")
        version = versions[0].strip().encode("utf-8")
    except (ValueError, UnicodeError) as error:
        result.obstacles.append(
            {
                "operation": "read_expected",
                "root": "subject",
                "path": case.spec.version_source,
                "reason": str(error),
            }
        )
        return
    if observed is not None and observed != version:
        mismatch(
            result,
            "content_mismatch",
            root,
            path,
            "exact retained distribution version bytes",
            "different version bytes",
        )


def _initial_absences(
    case: InstallTestCase, before: FilesystemSnapshot, result: VerificationResult
) -> None:
    dest = destinations(case)
    roots = destination_roots(case)
    for kind in ("skill", "references", "version"):
        require_absent(before, dest[kind], result, roots[kind])
    require_absent(before, dest["skill"] + ".bak", result, roots["skill"])
    if case.spec.json_hook_management == "registry":
        for path in sidecars(case).values():
            require_absent(before, path, result, roots["json"])
    if case.spec.json_backup is not None:
        require_absent(before, dest["json"] + case.spec.json_backup, result, roots["json"])


class InstallVerifier:
    def verify(
        self,
        case: InstallTestCase,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        after: FilesystemSnapshot,
        *,
        skill_backup: bytes | None = None,
        allow_registry_update: bool = False,
        allow_markdown_relocation: bool = False,
    ) -> VerificationResult:
        result = VerificationResult(
            obstacles=[
                ObservationObstacle(**o)
                for snapshot in (expected, before, after)
                for o in snapshot.obstacles
            ]
        )
        dest = destinations(case)
        skill = expected_file(expected, case.spec.skill_source, result)
        if skill is not None:
            compare_bytes(after, dest["skill"], skill, result, destination_roots(case)["skill"])
        _references(case, expected, after, result)
        _version(case, expected, after, result)
        self._shared_files(case, expected, before, after, result, allow_markdown_relocation)
        _json_backup(case, before, after, result)
        _preservation(case, expected, before, after, result, skill_backup)
        if skill_backup is not None:
            compare_bytes(
                after,
                dest["skill"] + ".bak",
                skill_backup,
                result,
                destination_roots(case)["skill"],
            )
        else:
            require_absent(after, dest["skill"] + ".bak", result, destination_roots(case)["skill"])
        if case.spec.skill_lock is not None and expected.skill_lock is None:
            result.obstacles.append(
                {
                    "operation": "resolve_lock",
                    "root": "home",
                    "path": ".",
                    "reason": "Independent lock expectation unavailable",
                }
            )
        skill_lock(expected.skill_lock, before, after, result)
        _managed_json(case, before, after, result, allow_registry_update)
        _reinstall_stability(case, before, after, result)
        result.complete = not result.obstacles
        return result

    def verify_altered_reference(
        self,
        plan: AlteredReferencePlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Require precisely one altered file and preserve all other entries."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        root, path = plan["root"], plan["altered_path"]
        file(installed, path, result, root)
        compare_bytes(degraded, path, content, result, root)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for other_root, other_path in sorted(keys - {(root, path)}):
            preserved_entry(installed, degraded, other_root, other_path, result)
        result.complete = not result.obstacles
        return result

    def verify_missing_reference(
        self,
        plan: MissingReferencePlan,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
    ) -> VerificationResult:
        """Require one deletion while preserving every other entry in both roots."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        key = (plan["root"], plan["deleted_path"])
        file(installed, plan["deleted_path"], result, plan["root"])
        require_absent(degraded, plan["deleted_path"], result, plan["root"])
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, path in sorted(keys - {key}):
            preserved_entry(installed, degraded, root, path, result)
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
        require_absent(degraded, plan["deleted_path"], result)
        compare_bytes(degraded, plan["altered_path"], content, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, path in sorted(keys):
            if root == "project" and path in (plan["deleted_path"], plan["altered_path"]):
                continue
            preserved_entry(installed, degraded, root, path, result)
        result.complete = not result.obstacles
        return result

    def verify_skill_repair(
        self,
        plan: FileAlterationPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        degraded: FilesystemSnapshot,
        root: str = "project",
    ) -> VerificationResult:
        """Require exactly the skill alteration and no backup or other change."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
        )
        compare_bytes(degraded, plan["altered_path"], content, result, root)
        require_absent(degraded, plan["altered_path"] + ".bak", result, root)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for entry_root, path in sorted(keys):
            if (entry_root, path) != (root, plan["altered_path"]):
                preserved_entry(installed, degraded, entry_root, path, result)
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
        root = destination_roots(case)["markdown"]
        compare_bytes(degraded, plan["altered_path"], content, result, root)
        previous = file(installed, plan["altered_path"], result, root)
        if previous is not None:
            _check_markdown_alteration(case, previous, content, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for entry_root, path in sorted(keys):
            if (entry_root, path) != (root, plan["altered_path"]):
                preserved_entry(installed, degraded, entry_root, path, result)
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
        if case.name in {
            "repair-missing-json-hook",
            "repair-altered-json-hook",
            "repair-duplicate-json-hook",
        }:
            return _verify_hook_preparation(case, plan, installed, degraded)
        path = plan["altered_path"]
        observed = file(degraded, path, result)
        previous = file(installed, path, result)
        if observed is not None:
            _json_preparation(content, observed, previous, path, result)
        if previous is not None:
            _json(case, content, previous, result)
        keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
        for root, entry_path in sorted(keys):
            if (root, entry_path) != ("project", path):
                preserved_entry(installed, degraded, root, entry_path, result)
        result.complete = not result.obstacles
        return result

    def verify_skill_backup(
        self,
        plan: SkillBackupPlan,
        content: bytes,
        installed: FilesystemSnapshot,
        prepared: FilesystemSnapshot,
        root: str = "project",
    ) -> VerificationResult:
        """Require exactly the new backup, with every existing entry unchanged."""
        result = VerificationResult(
            obstacles=[ObservationObstacle(**o) for s in (installed, prepared) for o in s.obstacles]
        )
        require_absent(installed, plan["backup_path"], result, root)
        compare_bytes(prepared, plan["backup_path"], content, result, root)
        keys = {(e["root"], e["path"]) for s in (installed, prepared) for e in s.entries}
        for entry_root, path in sorted(keys):
            if (entry_root, path) != (root, plan["backup_path"]):
                preserved_entry(installed, prepared, entry_root, path, result)
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
            expected_file(expected, source, result)
        if case.spec.version_source is not None:
            expected_file(expected, case.spec.version_source, result)
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
        _initial_absences(case, before, result)
        result.complete = not result.obstacles
        return result

    def _shared_files(
        self,
        case: InstallTestCase,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        after: FilesystemSnapshot,
        result: VerificationResult,
        allow_markdown_relocation: bool,
    ) -> None:
        dest = destinations(case)
        source = expected_file(expected, case.spec.markdown_source, result)
        for kind in ("markdown", "json"):
            path = dest[kind]
            root = destination_roots(case)[kind]
            initial = before.contents.get((root, path))
            installed = file(after, path, result, root)
            if initial is None or installed is None:
                continue
            if kind == "markdown" and source is not None:
                _markdown(case, source, initial, installed, result, allow_markdown_relocation)
            elif kind == "json":
                _json(case, initial, installed, result)


def _managed_json(
    case: InstallTestCase,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
    allow_registry_update: bool,
) -> None:
    if case.spec.json_hook_management == "none":
        return
    root = destination_roots(case)["json"]
    paths = sidecars(case)
    content = file(after, paths["state"], result, root)
    if content is not None:
        try:
            state = read_json(content)
            if not json_equal(state, registry(case)):
                raise ValueError("Registry differs from independent managed effects")
        except (ValueError, UnicodeError) as error:
            mismatch(
                result,
                "managed_registry",
                root,
                paths["state"],
                "exact independent registry",
                str(error),
            )
    _managed_hook_contents(case, after, result)
    compare_bytes(after, paths["lock"], b"", result, root)
    require_absent(after, paths["journal"], result, root)
    require_absent(after, destinations(case)["json"] + ".bak", result, root)
    old = before.contents.get((root, paths["state"]))
    if not allow_registry_update and old is not None and content != old:
        mismatch(
            result,
            "registry_stability",
            root,
            paths["state"],
            "unchanged registry bytes",
            "different registry bytes",
        )


def _managed_hook_contents(
    case: InstallTestCase, after: FilesystemSnapshot, result: VerificationResult
) -> None:
    path = destinations(case)["json"]
    root = destination_roots(case)["json"]
    content = after.contents.get((root, path))
    if content is None:
        return
    try:
        document = read_json(content)
        for hook in case.spec.json_hooks:
            exact = sum(
                json_equal(value, hook.content)
                for _, value in _hook_entries(document, hook.event, hook.matcher)
            )
            if exact != 1:
                mismatch(
                    result,
                    "managed_hook_content",
                    root,
                    path,
                    "one exact entire managed hook",
                    str(exact),
                )
    except (ValueError, UnicodeError):
        return  # The shared JSON verifier reports malformed documents separately.


def _restored_json(
    original: bytes, observed: bytes | None, root: str, path: str, result: VerificationResult
) -> None:
    if observed is None:
        return
    try:
        same = json_equal(read_json(original), read_json(observed))
    except (ValueError, UnicodeError):
        same = False
    if not same:
        mismatch(result, "content_mismatch", root, path, "unchanged JSON content", "changed JSON")


def _verify_hook_preparation(
    case: InstallTestCase,
    plan: FileAlterationPlan,
    installed: FilesystemSnapshot,
    degraded: FilesystemSnapshot,
) -> VerificationResult:
    result = VerificationResult(
        obstacles=[ObservationObstacle(**o) for s in (installed, degraded) for o in s.obstacles]
    )
    root, path = destination_roots(case)["json"], plan["altered_path"]
    previous = file(installed, path, result, root)
    observed = file(degraded, path, result, root)
    if previous is not None:
        try:
            document = read_json(previous)
            transform_json_hook(case, document)
            _restored_json(json.dumps(document).encode(), observed, root, path, result)
        except (ValueError, UnicodeError, KeyError, TypeError):
            mismatch(result, "invalid_preparation", root, path, "one declared hook", "invalid hook")
    keys = {(e["root"], e["path"]) for s in (installed, degraded) for e in s.entries}
    for entry_root, entry_path in sorted(keys):
        if (entry_root, entry_path) != (root, path):
            preserved_entry(installed, degraded, entry_root, entry_path, result)
    result.complete = not result.obstacles
    return result


def _hook_projection(case: InstallTestCase, value: dict[str, object]) -> dict[str, object]:
    document = deepcopy(value)
    hook = case.spec.json_hooks[0]
    events = cast(dict[str, object], document["hooks"])
    groups = cast(list[dict[str, object]], events[hook.event])
    empty: dict[str, object] = {"matcher": hook.matcher, "hooks": []}
    # Empty groups already present are personal witnesses, not managed objects.
    initial_empty = {index for index, group in enumerate(groups) if json_equal(group, empty)}
    remove_json_hook(case, document)
    events[hook.event] = [
        group
        for index, group in enumerate(groups)
        if index in initial_empty or not json_equal(group, empty)
    ]
    return document


def _same_hook_json(
    case: InstallTestCase, original: dict[str, object], observed: dict[str, object]
) -> bool:
    hook = case.spec.json_hooks[0]
    if any(
        len(hook_positions(value, hook.event, hook.matcher, hook.content, exact=False)) != 1
        for value in (original, observed)
    ):
        return False
    expected, current = (_hook_projection(case, value) for value in (original, observed))
    if json_equal(expected, current):
        return True
    return _vacated_group_matches(case, original, expected, current)


def _vacated_group_matches(
    case: InstallTestCase,
    original: dict[str, object],
    expected: dict[str, object],
    current: dict[str, object],
) -> bool:
    """Allow at most one empty residue of an observed bare managed search group."""
    if case.name not in {"repair-altered-json-hook", "repair-duplicate-json-hook"}:
        return False
    hook = case.spec.json_hooks[0]
    original_events = cast(dict[str, object], original["hooks"])
    original_groups = cast(list[object], original_events[hook.event])
    carrier = {"matcher": hook.matcher, "hooks": [hook.content]}
    if not any(json_equal(group, carrier) for group in original_groups):
        return False
    events = cast(dict[str, object], current["hooks"])
    groups = cast(list[object], events[hook.event])
    empty: dict[str, object] = {"matcher": hook.matcher, "hooks": []}
    return any(
        json_equal(
            expected,
            {**current, "hooks": {**events, hook.event: groups[:index] + groups[index + 1 :]}},
        )
        for index, group in enumerate(groups)
        if json_equal(group, empty)
    )


def _restored_hook_json(
    case: InstallTestCase,
    original: bytes,
    observed: bytes | None,
    root: str,
    path: str,
    result: VerificationResult,
) -> None:
    if observed is None:
        return
    try:
        same = _same_hook_json(case, read_json(original), read_json(observed))
    except (ValueError, UnicodeError, KeyError, TypeError):
        same = False
    if not same:
        mismatch(
            result,
            "content_mismatch",
            root,
            path,
            "preserved JSON and restored hook",
            "changed JSON",
        )
