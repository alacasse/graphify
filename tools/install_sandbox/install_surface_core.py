from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Protocol

try:
    from .expected_effects import (
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        SkillSidecarExpectation,
        TextExpectation,
        is_json_effect,
        is_skill_effect,
    )
    from .json_helpers import object_dict, object_dicts, object_list
    from .reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import (  # type: ignore[no-redef]
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonPluginExpectation,
        SkillSidecarExpectation,
        TextExpectation,
        is_json_effect,
        is_skill_effect,
    )
    from json_helpers import object_dict, object_dicts, object_list  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus  # type: ignore[no-redef]


USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"


@dataclass(frozen=True)
class InstallSurfaceStatus:
    path: Path
    ok: bool
    detail: str


@dataclass(frozen=True)
class GeneratedFileObservation:
    root_name: str
    relative: Path
    suffix: str
    file_size: int | None
    mentions_expected_marker: bool
    expected_key: bool
    skill_sidecar_relative: bool
    excluded_path: bool
    relative_substring_match: bool
    small_text_candidate: bool

    @property
    def path_relevant(self) -> bool:
        return self.expected_key or self.skill_sidecar_relative or self.relative_substring_match

    @property
    def needs_text_marker_match(self) -> bool:
        return not self.excluded_path and not self.path_relevant and self.small_text_candidate


@dataclass(frozen=True)
class GeneratedFileDecision:
    observation: GeneratedFileObservation
    is_relevant: bool
    is_ignored: bool

    @property
    def should_include(self) -> bool:
        return self.is_relevant and not self.is_ignored


@dataclass(frozen=True)
class StateEntryPlan:
    root_name: str
    relative: Path
    key: str
    marker: str | None = None
    text_expectation: TextExpectation | None = None


class GeneratedFileExpectationLike(Protocol):
    relative_substrings: tuple[str, ...]
    text_suffixes: tuple[str, ...]
    content_markers: tuple[str, ...]
    include_user_content_sentinel: bool
    max_text_bytes: int


ReferenceSidecarMode = Literal["absent", "source_error", "installed_directory"]


@dataclass(frozen=True)
class ReferenceSidecarExpectation:
    status: ReferenceResolutionStatus
    mode: ReferenceSidecarMode
    expected_names: tuple[str, ...]
    detail: str

    @classmethod
    def from_resolution(cls, resolution: PackagedReferenceResolution) -> ReferenceSidecarExpectation:
        if resolution.status in {"intentionally_absent", "no_eligible_bundle"}:
            mode: ReferenceSidecarMode = "absent"
        elif resolution.status in {"missing", "not_directory"}:
            mode = "source_error"
        else:
            mode = "installed_directory"
        return cls(
            status=resolution.status,
            mode=mode,
            expected_names=resolution.expected_names,
            detail=resolution.detail,
        )

    @property
    def includes_reference_dir(self) -> bool:
        return self.mode in {"source_error", "installed_directory"}

    def expected_relatives(self, skill_relative_dir: Path, sidecar: SkillSidecarExpectation) -> set[Path]:
        if not self.includes_reference_dir:
            return set()
        references = skill_relative_dir / sidecar.references_dir
        relatives = {references}
        relatives.update(references / name for name in self.expected_names)
        return relatives


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative


def skill_sidecar_expectation(surface: InstallSurface) -> SkillSidecarExpectation:
    if surface.skill_sidecar_expectation is None:
        raise AssertionError(f"expected path has no skill sidecar expectation: {surface.root}/{surface.relative}")
    return surface.skill_sidecar_expectation


def skill_dir_for_entry(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_surface_path(surface, roots).parent


def skill_relative_dir(surface: InstallSurface) -> Path:
    return Path(surface.relative).parent


def skill_version_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).version_name


def skill_references_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).references_dir


def skill_references_tmp_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).references_tmp_dir


def reference_sidecar_expectation(resolution: PackagedReferenceResolution) -> ReferenceSidecarExpectation:
    return ReferenceSidecarExpectation.from_resolution(resolution)


def expected_skill_sidecar_relatives(surface: InstallSurface, resolution: PackagedReferenceResolution) -> set[Path]:
    sidecar = skill_sidecar_expectation(surface)
    relatives = {
        skill_version_relative(surface),
        skill_references_tmp_relative(surface),
    }
    relatives.update(reference_sidecar_expectation(resolution).expected_relatives(skill_relative_dir(surface), sidecar))
    return relatives


def expected_generated_relative_keys(expected: Iterable[InstallSurface], resolution: PackagedReferenceResolution) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for surface in expected:
        keys.add((surface.root, surface.relative))
        if is_skill_effect(surface):
            for relative in expected_skill_sidecar_relatives(surface, resolution):
                keys.add((surface.root, relative.as_posix()))
    return keys


def planned_state_entries(
    expected: Iterable[InstallSurface],
    resolution: PackagedReferenceResolution,
    *,
    installed_skill_reference_relatives: Mapping[tuple[str, str], Iterable[Path]] | None = None,
) -> tuple[StateEntryPlan, ...]:
    installed_relatives = installed_skill_reference_relatives or {}
    entries: list[StateEntryPlan] = []
    for surface in expected:
        entries.append(
            StateEntryPlan(
                root_name=surface.root,
                relative=Path(surface.relative),
                key=f"{surface.root}/{surface.relative}",
                marker=surface.marker,
                text_expectation=surface.text_expectation,
            )
        )
        if not is_skill_effect(surface):
            continue
        sidecar_relatives = set(expected_skill_sidecar_relatives(surface, resolution))
        sidecar_relatives.update(installed_relatives.get((surface.root, surface.relative), ()))
        for relative in sorted(sidecar_relatives, key=lambda item: item.as_posix()):
            entries.append(
                StateEntryPlan(
                    root_name=surface.root,
                    relative=relative,
                    key=f"{surface.root}/{relative.as_posix()}",
                )
            )
    return tuple(entries)


def is_excluded_generated_path(relative: Path, excludes: Iterable[str]) -> bool:
    excluded_parts = set(excludes)
    return any(part in excluded_parts for part in relative.parts)


def is_expected_generated_key(expected: Iterable[InstallSurface], root_name: str, relative: Path) -> bool:
    return any(surface.root == root_name and surface.relative == relative.as_posix() for surface in expected)


def is_skill_sidecar_relative(expected: Iterable[InstallSurface], root_name: str, relative: Path) -> bool:
    for surface in expected:
        if root_name != surface.root or not is_skill_effect(surface):
            continue
        if relative == skill_version_relative(surface):
            return True
        for sidecar_dir in (skill_references_relative(surface), skill_references_tmp_relative(surface)):
            try:
                relative.relative_to(sidecar_dir)
                return True
            except ValueError:
                pass
    return False


def is_small_text_candidate(expectation: GeneratedFileExpectationLike, *, file_size: int, suffix: str) -> bool:
    if file_size > expectation.max_text_bytes:
        return False
    return suffix in expectation.text_suffixes


def text_mentions_expected_generated_marker(expectation: GeneratedFileExpectationLike, text: str) -> bool:
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in expectation.content_markers):
        return True
    return expectation.include_user_content_sentinel and USER_SENTINEL in text


def generated_file_observation(
    expectation: GeneratedFileExpectationLike,
    expected: Iterable[InstallSurface],
    root_name: str,
    relative: Path,
    *,
    file_size: int | None,
    mentions_expected_marker: bool,
    excluded_path: bool,
) -> GeneratedFileObservation:
    rel = relative.as_posix()
    return GeneratedFileObservation(
        root_name=root_name,
        relative=relative,
        suffix=relative.suffix,
        file_size=file_size,
        mentions_expected_marker=mentions_expected_marker,
        expected_key=is_expected_generated_key(expected, root_name, relative),
        skill_sidecar_relative=is_skill_sidecar_relative(expected, root_name, relative),
        excluded_path=excluded_path,
        relative_substring_match=any(fragment.lower() in rel.lower() for fragment in expectation.relative_substrings),
        small_text_candidate=file_size is not None and is_small_text_candidate(expectation, file_size=file_size, suffix=relative.suffix),
    )


def decide_generated_file_observation(observation: GeneratedFileObservation) -> GeneratedFileDecision:
    relevant = observation.path_relevant or (observation.small_text_candidate and observation.mentions_expected_marker)
    return GeneratedFileDecision(
        observation=observation,
        is_relevant=relevant,
        is_ignored=observation.excluded_path,
    )


def is_relevant_generated_file(
    expectation: GeneratedFileExpectationLike,
    expected: Iterable[InstallSurface],
    root_name: str,
    relative: Path,
    *,
    small_text_candidate: bool,
    mentions_expected_marker: bool,
) -> bool:
    rel = relative.as_posix()
    observation = GeneratedFileObservation(
        root_name=root_name,
        relative=relative,
        suffix=relative.suffix,
        file_size=0 if small_text_candidate else None,
        mentions_expected_marker=mentions_expected_marker,
        expected_key=is_expected_generated_key(expected, root_name, relative),
        skill_sidecar_relative=is_skill_sidecar_relative(expected, root_name, relative),
        excluded_path=False,
        relative_substring_match=any(fragment.lower() in rel.lower() for fragment in expectation.relative_substrings),
        small_text_candidate=small_text_candidate,
    )
    return decide_generated_file_observation(observation).is_relevant


def skill_version_status(version_text: str | None, expected_version: str) -> tuple[bool, str]:
    if version_text is None:
        return False, f"missing; expected={expected_version}"
    actual_version = version_text.strip()
    return actual_version == expected_version, f"actual={actual_version}; expected={expected_version}"


def references_tmp_absence_status(exists: bool) -> tuple[bool, str]:
    return not exists, "present" if exists else "absent"


def installed_reference_sidecar_status(
    expectation: ReferenceSidecarExpectation,
    *,
    references_exists: bool,
    references_is_dir: bool,
    installed_names: Iterable[str],
) -> tuple[bool, str]:
    expected_names = list(expectation.expected_names)
    if expectation.mode == "absent":
        refs_ok = not references_exists
        refs_state = "references_absent" if refs_ok else "references_present"
        return refs_ok, f"{expectation.status}; {refs_state}; {expectation.detail}"
    if expectation.mode == "source_error":
        return False, f"{expectation.status}; {expectation.detail}"
    if not references_exists:
        return False, f"references_missing; status={expectation.status}; expected_names={expected_names}; {expectation.detail}"
    if not references_is_dir:
        return False, f"references_not_directory; status={expectation.status}; expected_names={expected_names}; {expectation.detail}"

    actual_names = list(installed_names)
    missing = sorted(set(expected_names) - set(actual_names))
    extra = sorted(set(actual_names) - set(expected_names))
    refs_ok = not missing and not extra
    refs_detail = f"status={expectation.status}; actual_names={actual_names}; expected_names={expected_names}; missing={missing}; extra={extra}"
    return refs_ok, refs_detail


def skill_reference_pointers(sidecar: SkillSidecarExpectation, skill_text: str) -> list[str]:
    return sorted(set(re.findall(sidecar.reference_pointer_pattern, skill_text)))


def skill_reference_pointer_status(
    sidecar: SkillSidecarExpectation,
    skill_text: str,
    *,
    references_is_dir: bool,
    installed_names: Iterable[str],
) -> tuple[bool, str]:
    mentions_references = bool(re.search(sidecar.reference_pointer_pattern, skill_text)) or f"{sidecar.references_dir}/" in skill_text
    pointers = skill_reference_pointers(sidecar, skill_text)
    if mentions_references and not references_is_dir:
        return False, f"{sidecar.references_dir}_missing; skill_mentions_references=true; pointers={pointers}"
    if pointers:
        installed = set(installed_names)
        missing_pointers = [name for name in pointers if name not in installed]
        return not missing_pointers, f"pointers={pointers}; missing={missing_pointers}"
    return True, "no_reference_pointers"


def uninstalled_skill_sidecar_status(exists: bool) -> tuple[bool, str]:
    return not exists, "sidecar_still_exists" if exists else "removed"


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


def file_fingerprint(path: Path, marker: str | None = None, text_expectation: TextExpectation | None = None) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    if path.is_dir():
        return {"exists": True, "kind": "dir"}
    data = path.read_bytes()
    item: dict[str, object] = {"exists": True, "kind": "file", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if marker:
        text = data.decode("utf-8", errors="replace")
        item["marker_count"] = text.count(marker)
        expectation = text_expectation or TextExpectation()
        if expectation.preserve_user_content:
            item["user_content_preserved"] = USER_SENTINEL in text
        if expectation.repair_stale_graphify_section:
            item["stale_graphify_present"] = STALE_GRAPHIFY_SENTINEL in text
    return item
