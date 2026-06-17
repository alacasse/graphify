from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    from .expected_effects import (
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        is_json_effect,
    )
    from .json_helpers import object_dict, object_dicts, object_list
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import (  # type: ignore[no-redef]
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        is_json_effect,
    )
    from json_helpers import object_dict, object_dicts, object_list  # type: ignore[no-redef]


USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"


@dataclass(frozen=True)
class InstallSurfaceStatus:
    path: Path
    ok: bool
    detail: str


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative


def expected_kind_status(path: Path, kind: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if kind == "file":
        return path.is_file(), "file" if path.is_file() else "expected_file_but_not_file"
    if kind == "dir":
        return path.is_dir(), "directory" if path.is_dir() else "expected_directory_but_not_directory"
    return True, "exists"


def install_surface_kind_status(surface: InstallSurface, roots: Mapping[str, Path]) -> InstallSurfaceStatus:
    path = resolve_install_surface_path(surface, roots)
    ok, detail = expected_kind_status(path, surface.kind)
    return InstallSurfaceStatus(path, ok, detail)


def json_value_contains_marker(value: object, marker: str) -> bool:
    if isinstance(value, dict):
        return any(marker in str(key) or json_value_contains_marker(item, marker) for key, item in value.items())
    if isinstance(value, list):
        return any(json_value_contains_marker(item, marker) for item in value)
    if isinstance(value, str):
        return marker in value
    return False


def command_hook_present(entry: object, expectation: JsonHookExpectation) -> bool:
    entry_data = object_dict(entry)
    if entry_data.get("matcher") != expectation.matcher:
        return False
    for hook in object_dicts(entry_data.get("hooks")):
        if hook.get("type") != "command":
            continue
        command = hook.get("command")
        if isinstance(command, str) and all(fragment in command for fragment in expectation.required_fragments):
            return True
    return False


def hooks_by_event(data: object, event_name: str) -> list[object]:
    hooks = object_dict(object_dict(data).get("hooks"))
    return object_list(hooks.get(event_name))


def plugin_config_present(data: object, expectation: JsonPluginExpectation) -> bool:
    plugins = object_list(object_dict(data).get("plugin"))
    for plugin in plugins:
        if not isinstance(plugin, str):
            continue
        if plugin == expectation.expected_entry:
            return True
        if expectation.allow_file_uri and plugin.startswith("file://") and plugin.endswith(expectation.expected_entry):
            return True
    return False


def json_expectation_status(data: object, expectation: JsonExpectation) -> tuple[bool, str]:
    states: list[tuple[str, bool]] = []
    for hook in expectation.hooks:
        entries = hooks_by_event(data, hook.event)
        states.append((hook.detail_name, any(command_hook_present(entry, hook) for entry in entries)))
    if expectation.plugin is not None:
        states.append((expectation.plugin.detail_name, plugin_config_present(data, expectation.plugin)))
    ok = all(present for _, present in states)
    detail = f"valid_json=true; schema={expectation.schema_name}"
    for name, present in states:
        detail += f"; {name}={present}"
    return ok, detail


def json_marker_status(path: Path, surface: InstallSurface) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid_json={exc.msg}"
    except OSError as exc:
        return False, f"json_read_failed={exc}"
    if surface.json_expectation is not None:
        return json_expectation_status(data, surface.json_expectation)
    marker = surface.marker or ""
    marker_present = bool(marker) and json_value_contains_marker(data, marker)
    return marker_present, f"valid_json=true; schema=generic_marker; marker_present={marker_present}"


def expects_user_content_preserved(surface: InstallSurface) -> bool:
    return surface.text_expectation.preserve_user_content


def expects_stale_graphify_section_repaired(surface: InstallSurface) -> bool:
    return surface.text_expectation.repair_stale_graphify_section


def text_marker_status(path: Path, surface: InstallSurface) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    marker_count = text.count(surface.marker or "")
    ok = marker_count == 1
    detail = f"marker_count={marker_count}"
    if USER_SENTINEL in text:
        detail += "; user_content_preserved"
    elif expects_user_content_preserved(surface):
        ok = False
        detail += "; user_content_missing"
    if expects_stale_graphify_section_repaired(surface):
        stale_replaced = STALE_GRAPHIFY_SENTINEL not in text
        ok = ok and stale_replaced
        detail += f"; stale_replaced={stale_replaced}"
    return ok, detail


def installed_surface_status(surface: InstallSurface, roots: Mapping[str, Path]) -> InstallSurfaceStatus:
    status = install_surface_kind_status(surface, roots)
    if not status.ok or not surface.marker:
        return status
    if is_json_effect(surface):
        ok, detail = json_marker_status(status.path, surface)
    else:
        ok, detail = text_marker_status(status.path, surface)
    return InstallSurfaceStatus(status.path, ok, detail)


def graphify_section_removed(text: str, surface: InstallSurface) -> bool:
    marker_removed = not surface.marker or surface.marker not in text
    stale_removed = not surface.text_expectation.repair_stale_graphify_section or STALE_GRAPHIFY_SENTINEL not in text
    return marker_removed and stale_removed


def uninstalled_surface_status(surface: InstallSurface, roots: Mapping[str, Path]) -> InstallSurfaceStatus:
    path = resolve_install_surface_path(surface, roots)
    text_expectation = surface.text_expectation
    if surface.marker and text_expectation.require_user_content_on_uninstall:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            graphify_removed = graphify_section_removed(text, surface)
            user_preserved = USER_SENTINEL in text
            return InstallSurfaceStatus(path, graphify_removed and user_preserved, f"graphify_removed={graphify_removed}; user_content_preserved={user_preserved}")
        return InstallSurfaceStatus(path, False, "user_content_file_missing")
    if surface.marker and text_expectation.remove_graphify_section_on_uninstall and path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        ok = graphify_section_removed(text, surface)
        detail = "graphify_removed; user_content_preserved" if USER_SENTINEL in text else "graphify_removed"
        return InstallSurfaceStatus(path, ok, detail)
    ok = not path.exists()
    return InstallSurfaceStatus(path, ok, "removed" if ok else "still_exists")
