"""Mutate and compare a declared hook without interpreting command strings."""

from typing import cast

from tools.install_sandbox.contracts.effects import JsonHooksEffect
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.rules.comparison import group_hooks, json_equal, read_json
from tools.install_sandbox.rules.lossless_json import encode_json


def event_groups(document: dict[str, object], event: str) -> list[object]:
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError("Expected hooks object")
    groups = cast(dict[str, object], hooks).get(event)
    if not isinstance(groups, list):
        raise ValueError("Expected declared event group list")
    return cast(list[object], groups)


def target_location(document: dict[str, object], target: HookExpectation) -> tuple[int, int]:
    groups = event_groups(document, target.event)
    matches: list[tuple[int, int]] = []
    for group_index, raw in enumerate(groups):
        if not isinstance(raw, dict):
            raise ValueError("Expected hook group object")
        group = cast(dict[str, object], raw)
        if group.get("matcher") != target.matcher:
            continue
        for hook_index, (_, hook) in enumerate(group_hooks(group, target.event)):
            if all(
                key in hook and json_equal(hook[key], value)
                for key, value in target.content.items()
            ):
                matches.append((group_index, hook_index))
    if len(matches) != 1:
        raise ValueError("Expected exactly one conforming target hook")
    return matches[0]


def _copy_hook_path(
    document: dict[str, object], event: str, group_index: int
) -> tuple[dict[str, object], list[dict[str, object]], list[object]]:
    """Copy only ancestors of the hook list; all retained descendants stay untouched."""
    original_groups = event_groups(document, event)
    if any(not isinstance(group, dict) for group in original_groups):
        raise ValueError("Expected hook group object")
    result = document.copy()
    hooks = cast(dict[str, object], document["hooks"]).copy()
    groups = cast(list[dict[str, object]], original_groups).copy()
    group = groups[group_index].copy()
    raw_contents = group["hooks"]
    if not isinstance(raw_contents, list):
        raise ValueError("Expected hook list")
    contents = list(cast(list[object], raw_contents))
    result["hooks"] = hooks
    hooks[event] = groups
    groups[group_index] = group
    group["hooks"] = contents
    return result, groups, contents


def without_target(
    document: dict[str, object], target: HookExpectation, *, drop_empty_group: bool = False
) -> dict[str, object]:
    group_index, hook_index = target_location(document, target)
    result, groups, contents = _copy_hook_path(document, target.event, group_index)
    group = groups[group_index]
    del contents[hook_index]
    if drop_empty_group and not contents and set(group) == {"matcher", "hooks"}:
        del groups[group_index]
    return result


def missing_hook_settings(effect: JsonHooksEffect, installed: bytes) -> bytes:
    """Remove only the first declared hook's unique observed object."""
    if not effect.hooks:
        raise ValueError("JSON repair requires a declared hook")
    prepared = without_target(read_json(installed), effect.hooks[0])
    return (encode_json(prepared) + "\n").encode("utf-8")


def _altered_timeout(target: HookExpectation) -> int:
    timeout = target.content.get("timeout")
    if type(timeout) is not int:
        raise ValueError("JSON hook alteration requires a declared integer timeout")
    return timeout + 1


def altered_hook_settings(effect: JsonHooksEffect, installed: bytes) -> bytes:
    """Change only the unique observed target's declared integer timeout by one."""
    if not effect.hooks:
        raise ValueError("JSON repair requires a declared hook")
    target = effect.hooks[0]
    timeout = _altered_timeout(target)
    document = read_json(installed)
    group_index, hook_index = target_location(document, target)
    prepared, _, contents = _copy_hook_path(document, target.event, group_index)
    hook = cast(dict[str, object], contents[hook_index]).copy()
    hook["timeout"] = timeout
    contents[hook_index] = hook
    return (encode_json(prepared) + "\n").encode("utf-8")


def prepared_hook_settings(effect: JsonHooksEffect, installed: bytes, kind: str) -> bytes:
    """Dispatch only supported hook preparations."""
    if kind == "missing-json-hook":
        return missing_hook_settings(effect, installed)
    if kind == "altered-json-hook":
        return altered_hook_settings(effect, installed)
    if kind == "duplicate-json-hook":
        return duplicated_hook_settings(effect, installed)
    raise ValueError("Unsupported JSON hook preparation")


def altered_target_preserved(
    original: dict[str, object], prepared: dict[str, object], target: HookExpectation
) -> bool:
    """Restore the timeout at its observed position and compare independently."""
    timeout = _altered_timeout(target)
    group_index, hook_index = target_location(original, target)
    try:
        restored, _, contents = _copy_hook_path(prepared, target.event, group_index)
        candidate = contents[hook_index]
        if not isinstance(candidate, dict):
            return False
        hook = cast(dict[str, object], candidate).copy()
        if "timeout" not in hook or not json_equal(hook["timeout"], timeout):
            return False
        hook["timeout"] = target.content["timeout"]
        contents[hook_index] = hook
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return json_equal(original, restored)


def repaired_json_preserved(
    prepared: dict[str, object], current: dict[str, object], target: HookExpectation
) -> bool:
    """Accept a target inserted in an existing group or a new matcher-only group."""
    removed = without_target(current, target)
    if json_equal(prepared, removed):
        return True
    return json_equal(prepared, without_target(current, target, drop_empty_group=True))


def target_group_preserved(
    before: dict[str, object], after: dict[str, object], target: HookExpectation
) -> bool:
    """Keep the selected target in the initial mixed group with its witnesses."""

    def personal_group(document: dict[str, object]) -> dict[str, object]:
        group_index, hook_index = target_location(document, target)
        events = cast(dict[str, object], document["hooks"])
        groups = cast(list[dict[str, object]], events[target.event])
        group = dict(groups[group_index])
        contents = list(cast(list[object], group["hooks"]))
        del contents[hook_index]
        group["hooks"] = contents
        return group

    return json_equal(personal_group(before), personal_group(after))


def removed_target_preserved(
    original: dict[str, object], prepared: dict[str, object], target: HookExpectation
) -> bool:
    """Reinsert the retained observed hook into the candidate and compare to its source."""
    group_index, hook_index = target_location(original, target)
    original_events = cast(dict[str, object], original["hooks"])
    original_groups = cast(list[dict[str, object]], original_events[target.event])
    observed_hook = cast(list[object], original_groups[group_index]["hooks"])[hook_index]
    try:
        restored, _, contents = _copy_hook_path(prepared, target.event, group_index)
        if hook_index > len(contents):
            return False
        contents.insert(hook_index, observed_hook)
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return json_equal(original, restored)


def _duplicate_destination(document: dict[str, object], target: HookExpectation) -> int:
    matches = [
        index
        for index, group in enumerate(event_groups(document, target.event))
        if isinstance(group, dict)
        and cast(dict[str, object], group).get("matcher") == target.matcher
        and cast(dict[str, object], group).get("sandbox_personal") == "duplicate-destination"
    ]
    if len(matches) != 1:
        raise ValueError("Expected unique marked duplicate destination group")
    return matches[0]


def duplicated_hook_settings(effect: JsonHooksEffect, installed: bytes) -> bytes:
    """Insert the full unique observed hook between the destination witnesses."""
    if not effect.hooks:
        raise ValueError("JSON repair requires a declared hook")
    target = effect.hooks[0]
    document = read_json(installed)
    group_index, hook_index = target_location(document, target)
    source = cast(dict[str, object], event_groups(document, target.event)[group_index])
    observed_hook = cast(list[object], source["hooks"])[hook_index]
    destination = _duplicate_destination(document, target)
    prepared, _, contents = _copy_hook_path(document, target.event, destination)
    if len(contents) != 2 or destination == group_index:
        raise ValueError("Expected two personal destination witnesses")
    contents.insert(1, observed_hook)
    return (encode_json(prepared) + "\n").encode("utf-8")


def duplicated_target_preserved(
    original: dict[str, object], prepared: dict[str, object], target: HookExpectation
) -> bool:
    """Undo only the observed copy, independently of preparation generation."""
    group_index, hook_index = target_location(original, target)
    source = cast(dict[str, object], event_groups(original, target.event)[group_index])
    observed_hook = cast(list[object], source["hooks"])[hook_index]
    try:
        destination = _duplicate_destination(prepared, target)
        restored, _, contents = _copy_hook_path(prepared, target.event, destination)
        if len(contents) != 3 or not json_equal(contents[1], observed_hook):
            return False
        del contents[1]
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return json_equal(original, restored)
