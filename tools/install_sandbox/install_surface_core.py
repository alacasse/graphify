from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Iterable, Literal, Mapping, Protocol

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
        is_text_section_effect,
    )
    from .json_helpers import object_dict, object_dicts, object_list
    from .reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus
    from .install_surface_sidecars import (
        ReferenceSidecarExpectation,
        ReferenceSidecarMode,
        expected_skill_sidecar_relatives,
        installed_reference_sidecar_status,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_reference_pointers,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_relative_dir,
        skill_sidecar_expectation,
        skill_version_relative,
        skill_version_status,
        uninstalled_skill_sidecar_status,
    )
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
        is_text_section_effect,
    )
    from json_helpers import object_dict, object_dicts, object_list  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus  # type: ignore[no-redef]
    from install_surface_sidecars import (  # type: ignore[no-redef]
        ReferenceSidecarExpectation,
        ReferenceSidecarMode,
        expected_skill_sidecar_relatives,
        installed_reference_sidecar_status,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_reference_pointers,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_relative_dir,
        skill_sidecar_expectation,
        skill_version_relative,
        skill_version_status,
        uninstalled_skill_sidecar_status,
    )


USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"


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
class GeneratedArtifactCopyPlan:
    root_name: str
    source_relative: Path
    destination_relative: Path


@dataclass(frozen=True)
class StateEntryPlan:
    root_name: str
    relative: Path
    key: str
    marker: str | None = None
    text_expectation: TextExpectation | None = None


@dataclass(frozen=True)
class IdempotencyStateChange:
    key: str
    stable: bool


@dataclass(frozen=True)
class UserContentSeedPlan:
    root_name: str
    relative: Path
    text: str


StaleSidecarSeedKind = Literal["stale_reference_fragment", "staged_reference_fragment"]


@dataclass(frozen=True)
class StaleSidecarSeedPlan:
    root_name: str
    relative: Path
    text: str
    kind: StaleSidecarSeedKind


class GeneratedFileExpectationLike(Protocol):
    relative_substrings: tuple[str, ...]
    text_suffixes: tuple[str, ...]
    content_markers: tuple[str, ...]
    include_user_content_sentinel: bool
    max_text_bytes: int


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative


def expected_manifest_relatives(
    surfaces: Iterable[InstallSurface],
    resolution: PackagedReferenceResolution,
    root_name: str,
) -> set[Path]:
    relatives: set[Path] = set()
    for surface in surfaces:
        if surface.root != root_name:
            continue
        relatives.add(Path(surface.relative))
        if is_skill_effect(surface):
            relatives.update(expected_skill_sidecar_relatives(surface, resolution))
    return relatives


def _planned_state_entries(
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


def expected_generated_relative_keys(expected: Iterable[InstallSurface], resolution: PackagedReferenceResolution) -> set[tuple[str, str]]:
    return {(entry.root_name, entry.relative.as_posix()) for entry in _planned_state_entries(expected, resolution)}


def planned_state_entries(
    expected: Iterable[InstallSurface],
    resolution: PackagedReferenceResolution,
    *,
    installed_skill_reference_relatives: Mapping[tuple[str, str], Iterable[Path]] | None = None,
) -> tuple[StateEntryPlan, ...]:
    return _planned_state_entries(
        expected,
        resolution,
        installed_skill_reference_relatives=installed_skill_reference_relatives,
    )


def idempotency_state_changes(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
) -> tuple[IdempotencyStateChange, ...]:
    return tuple(
        IdempotencyStateChange(key=key, stable=before.get(key) == after.get(key))
        for key in sorted(set(before) | set(after))
    )


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
    expected_keys: AbstractSet[tuple[str, str]] | None = None,
) -> GeneratedFileObservation:
    rel = relative.as_posix()
    return GeneratedFileObservation(
        root_name=root_name,
        relative=relative,
        suffix=relative.suffix,
        file_size=file_size,
        mentions_expected_marker=mentions_expected_marker,
        expected_key=(
            (root_name, rel) in expected_keys
            if expected_keys is not None
            else is_expected_generated_key(expected, root_name, relative)
        ),
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


def generated_artifact_copy_plan(root_name: str, source_relative: Path) -> GeneratedArtifactCopyPlan:
    return GeneratedArtifactCopyPlan(
        root_name=root_name,
        source_relative=source_relative,
        destination_relative=Path(root_name) / source_relative,
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


def expects_user_content_preserved(surface: InstallSurface) -> bool:
    return surface.text_expectation.preserve_user_content


def expects_stale_graphify_section_repaired(surface: InstallSurface) -> bool:
    return surface.text_expectation.repair_stale_graphify_section


def should_seed_user_content(surface: InstallSurface) -> bool:
    return is_text_section_effect(surface) and expects_user_content_preserved(surface)


def should_seed_stale_graphify_section(surface: InstallSurface) -> bool:
    return is_text_section_effect(surface) and expects_stale_graphify_section_repaired(surface)


def seeded_user_content_text(surface: InstallSurface) -> str:
    if should_seed_stale_graphify_section(surface) and surface.marker:
        return (
            f"# User Notes\n\n{USER_SENTINEL}\n\n"
            f"{surface.marker}\n{STALE_GRAPHIFY_SENTINEL}\n\n"
            "## User Section\nThis section should survive Graphify install and uninstall.\n"
        )
    return f"# User Notes\n\n{USER_SENTINEL}\n"


def user_content_seed_plans(surfaces: Iterable[InstallSurface]) -> tuple[UserContentSeedPlan, ...]:
    plans: list[UserContentSeedPlan] = []
    for surface in surfaces:
        if should_seed_user_content(surface):
            plans.append(
                UserContentSeedPlan(
                    root_name=surface.root,
                    relative=Path(surface.relative),
                    text=seeded_user_content_text(surface),
                )
            )
    return tuple(plans)


def stale_sidecar_seed_plans(
    surfaces: Iterable[InstallSurface],
    resolution: PackagedReferenceResolution,
) -> tuple[StaleSidecarSeedPlan, ...]:
    if not reference_sidecar_expectation(resolution).includes_reference_dir:
        return ()

    plans: list[StaleSidecarSeedPlan] = []
    for surface in surfaces:
        if not is_skill_effect(surface):
            continue
        plans.extend(
            (
                StaleSidecarSeedPlan(
                    root_name=surface.root,
                    relative=skill_references_relative(surface) / "stale-sandbox-fragment.md",
                    text="stale sandbox reference fragment\n",
                    kind="stale_reference_fragment",
                ),
                StaleSidecarSeedPlan(
                    root_name=surface.root,
                    relative=skill_references_tmp_relative(surface) / "partial.md",
                    text="partial staged reference fragment\n",
                    kind="staged_reference_fragment",
                ),
            )
        )
    return tuple(plans)


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
