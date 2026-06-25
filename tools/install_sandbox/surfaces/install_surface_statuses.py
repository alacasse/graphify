from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    from .install_surface_models import (
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        TextExpectation,
        is_json_effect,
    )
    from .install_surface_state import (
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        expects_stale_graphify_section_repaired,
        expects_user_content_preserved,
    )
    from ..json_helpers import object_dict, object_dicts, object_list
except ImportError:  # pragma: no cover - direct script import fallback
    from surfaces.install_surface_models import (  # type: ignore[no-redef]
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        TextExpectation,
        is_json_effect,
    )
    from surfaces.install_surface_state import (  # type: ignore[no-redef]
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        expects_stale_graphify_section_repaired,
        expects_user_content_preserved,
    )
    from json_helpers import object_dict, object_dicts, object_list  # type: ignore[no-redef]


@dataclass(frozen=True)
class InstallSurfaceStatus:
    path: Path
    ok: bool
    detail: str


@dataclass(frozen=True)
class InstallSurfaceObservation:
    path: Path
    exists: bool
    is_file: bool = False
    is_dir: bool = False
    text: str | None = None
    json_data: object = None
    json_loaded: bool = False
    json_error_detail: str | None = None


@dataclass(frozen=True)
class UninstallSurfaceObservation:
    path: Path
    exists: bool
    is_file: bool = False
    is_dir: bool = False
    text: str | None = None
    text_error_detail: str | None = None


@dataclass(frozen=True)
class FileFingerprintObservation:
    exists: bool
    kind: Literal["file", "dir"] | None = None
    data: bytes | None = None
    text: str | None = None


def expected_kind_status_from_observation(observation: InstallSurfaceObservation, kind: str) -> tuple[bool, str]:
    if not observation.exists:
        return False, "missing"
    if kind == "file":
        return observation.is_file, "file" if observation.is_file else "expected_file_but_not_file"
    if kind == "dir":
        return observation.is_dir, "directory" if observation.is_dir else "expected_directory_but_not_directory"
    return True, "exists"


def install_surface_kind_status_from_observation(
    surface: InstallSurface,
    observation: InstallSurfaceObservation,
) -> InstallSurfaceStatus:
    ok, detail = expected_kind_status_from_observation(observation, surface.kind)
    return InstallSurfaceStatus(observation.path, ok, detail)


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


def json_marker_status_from_observation(
    surface: InstallSurface,
    observation: InstallSurfaceObservation,
) -> tuple[bool, str]:
    if observation.json_error_detail is not None:
        return False, observation.json_error_detail
    if not observation.json_loaded:
        raise AssertionError(f"json observation has no data or error: {observation.path}")
    data = observation.json_data
    if surface.json_expectation is not None:
        return json_expectation_status(data, surface.json_expectation)
    marker = surface.marker or ""
    marker_present = bool(marker) and json_value_contains_marker(data, marker)
    return marker_present, f"valid_json=true; schema=generic_marker; marker_present={marker_present}"


def text_marker_status_from_text(text: str, surface: InstallSurface) -> tuple[bool, str]:
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


def installed_surface_status_from_observation(
    surface: InstallSurface,
    observation: InstallSurfaceObservation,
) -> InstallSurfaceStatus:
    status = install_surface_kind_status_from_observation(surface, observation)
    if not status.ok or not surface.marker:
        return status
    if is_json_effect(surface):
        ok, detail = json_marker_status_from_observation(surface, observation)
    else:
        if observation.text is None:
            raise AssertionError(f"text observation has no data: {observation.path}")
        ok, detail = text_marker_status_from_text(observation.text, surface)
    return InstallSurfaceStatus(status.path, ok, detail)


def graphify_section_removed(text: str, surface: InstallSurface) -> bool:
    marker_removed = not surface.marker or surface.marker not in text
    stale_removed = not surface.text_expectation.repair_stale_graphify_section or STALE_GRAPHIFY_SENTINEL not in text
    return marker_removed and stale_removed


def uninstalled_surface_status_from_observation(
    surface: InstallSurface,
    observation: UninstallSurfaceObservation,
) -> InstallSurfaceStatus:
    text_expectation = surface.text_expectation
    if surface.marker and text_expectation.require_user_content_on_uninstall:
        if observation.exists and observation.is_file:
            if observation.text_error_detail is not None:
                return InstallSurfaceStatus(observation.path, False, observation.text_error_detail)
            if observation.text is None:
                raise AssertionError(f"uninstall text observation has no data: {observation.path}")
            graphify_removed = graphify_section_removed(observation.text, surface)
            user_preserved = USER_SENTINEL in observation.text
            return InstallSurfaceStatus(
                observation.path,
                graphify_removed and user_preserved,
                f"graphify_removed={graphify_removed}; user_content_preserved={user_preserved}",
            )
        return InstallSurfaceStatus(observation.path, False, "user_content_file_missing")
    if surface.marker and text_expectation.remove_graphify_section_on_uninstall and observation.exists:
        if observation.text_error_detail is not None:
            return InstallSurfaceStatus(observation.path, False, observation.text_error_detail)
        if observation.text is None:
            raise AssertionError(f"uninstall text observation has no data: {observation.path}")
        ok = graphify_section_removed(observation.text, surface)
        detail = "graphify_removed; user_content_preserved" if USER_SENTINEL in observation.text else "graphify_removed"
        return InstallSurfaceStatus(observation.path, ok, detail)
    ok = not observation.exists
    return InstallSurfaceStatus(observation.path, ok, "removed" if ok else "still_exists")


def file_fingerprint_from_observation(
    observation: FileFingerprintObservation,
    marker: str | None = None,
    text_expectation: TextExpectation | None = None,
) -> dict[str, object]:
    if not observation.exists:
        return {"exists": False}
    if observation.kind == "dir":
        return {"exists": True, "kind": "dir"}
    if observation.data is None:
        raise AssertionError("file fingerprint observation has no bytes")
    data = observation.data
    item: dict[str, object] = {"exists": True, "kind": "file", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if marker:
        if observation.text is None:
            raise AssertionError("file fingerprint observation has no decoded text")
        text = observation.text
        item["marker_count"] = text.count(marker)
        expectation = text_expectation or TextExpectation()
        if expectation.preserve_user_content:
            item["user_content_preserved"] = USER_SENTINEL in text
        if expectation.repair_stale_graphify_section:
            item["stale_graphify_present"] = STALE_GRAPHIFY_SENTINEL in text
    return item
