"""Representation-level byte, Markdown and JSON comparison primitives."""

import json
from typing import cast

from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationMismatch, VerificationResult
from tools.install_sandbox.contracts.spec import HookExpectation


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


def verify_markdown_section(
    expected: bytes,
    before: bytes,
    after: bytes,
    result: VerificationResult,
    *,
    root: str,
    path: str,
    marker: str,
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
    if not preserved:
        mismatch(
            result,
            "user_content_lost",
            root,
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


def _managed_hook(
    hooks: tuple[HookExpectation, ...],
    event: str,
    group: dict[str, object],
    content: dict[str, object],
) -> bool:
    return any(
        hook.event == event
        and hook.matcher == group.get("matcher")
        and all(
            key in content and json_equal(content[key], value)
            for key, value in hook.content.items()
        )
        for hook in hooks
    )


def _personal_groups(
    hooks: tuple[HookExpectation, ...], event: str, groups: list[object]
) -> list[object]:
    result: list[object] = []
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Hook groups must be objects")
        group = cast(dict[str, object], raw)
        contents = group_hooks(group, event)
        personal = [
            content for _, content in contents if not _managed_hook(hooks, event, group, content)
        ]
        removed = len(personal) != len(contents)
        if removed and not personal and set(group) == {"matcher", "hooks"}:
            continue
        result.append({**group, "hooks": personal} if removed else group)
    return result


def personal_json(
    hooks: tuple[HookExpectation, ...], document: dict[str, object]
) -> dict[str, object]:
    result = dict(document)
    raw = document.get("hooks")
    if raw is None:
        return result
    if not isinstance(raw, dict):
        raise ValueError("hooks must be an object")
    events: dict[str, object] = {}
    for event, groups in cast(dict[str, object], raw).items():
        if not isinstance(groups, list):
            raise ValueError("Hook events must contain group lists")
        personal = _personal_groups(hooks, event, cast(list[object], groups))
        if personal or not groups:
            events[event] = personal
    if events or not raw:
        result["hooks"] = events
    else:
        result.pop("hooks", None)
    return result


def markdown_byte_parts(content: bytes, marker: str) -> tuple[bytes, bytes, bytes] | None:
    """Split one exact heading through its next level-one/two heading in bytes."""
    lines = content.splitlines(keepends=True)
    encoded = marker.encode("utf-8")
    starts = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == encoded]
    if len(starts) != 1:
        return None
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith((b"# ", b"## "))),
        len(lines),
    )
    return b"".join(lines[:start]), b"".join(lines[start:end]), b"".join(lines[end:])


def verify_markdown_composed(
    expected: bytes,
    exterior: bytes,
    after: bytes,
    result: VerificationResult,
    *,
    root: str,
    path: str,
    marker: str,
) -> None:
    """Require exact source and exterior bytes with unrestricted section placement."""
    parts = markdown_byte_parts(after, marker)
    if parts is None:
        mismatch(result, "section_count", root, path, "one section", "zero or multiple sections")
        return
    prefix, section, suffix = parts
    if section != expected:
        mismatch(result, "content_mismatch", root, path, "exact source section", "different bytes")
    if prefix + suffix != exterior:
        mismatch(result, "user_content_lost", root, path, "exact exterior bytes", "different bytes")
