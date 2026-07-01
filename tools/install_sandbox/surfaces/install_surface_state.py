from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

from .install_surface_models import InstallSurface, TextExpectation, is_skill_effect, is_text_section_effect
from .install_surface_sidecars import (
    expected_skill_sidecar_relatives,
    reference_sidecar_expectation,
    skill_references_relative,
    skill_references_tmp_relative,
)
from ..targets.reference_resolution import PackagedReferenceResolution


USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"

StaleSidecarSeedKind = Literal["stale_reference_fragment", "staged_reference_fragment"]


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


@dataclass(frozen=True)
class StaleSidecarSeedPlan:
    root_name: str
    relative: Path
    text: str
    kind: StaleSidecarSeedKind


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
