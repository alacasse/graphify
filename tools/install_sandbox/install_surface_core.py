from __future__ import annotations

from pathlib import Path
from typing import Mapping

try:
    from .expected_effects import (
        InstallSurface,
        SkillSidecarExpectation,
        is_skill_effect,
    )
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
    from .install_surface_generated import (
        GeneratedArtifactCopyPlan,
        GeneratedFileDecision,
        GeneratedFileExpectationLike,
        GeneratedFileObservation,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        is_expected_generated_key,
        is_relevant_generated_file,
        is_skill_sidecar_relative,
        is_small_text_candidate,
        text_mentions_expected_generated_marker,
    )
    from .install_surface_statuses import (
        FileFingerprintObservation,
        InstallSurfaceObservation,
        InstallSurfaceStatus,
        UninstallSurfaceObservation,
        command_hook_present,
        expected_kind_status_from_observation,
        file_fingerprint_from_observation,
        graphify_section_removed,
        hooks_by_event,
        install_surface_kind_status_from_observation,
        installed_surface_status_from_observation,
        json_expectation_status,
        json_marker_status_from_observation,
        json_value_contains_marker,
        plugin_config_present,
        text_marker_status_from_text,
        uninstalled_surface_status_from_observation,
    )
    from .install_surface_state import (
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        IdempotencyStateChange,
        StaleSidecarSeedKind,
        StaleSidecarSeedPlan,
        StateEntryPlan,
        UserContentSeedPlan,
        expected_generated_relative_keys,
        expected_manifest_relatives,
        expects_stale_graphify_section_repaired,
        expects_user_content_preserved,
        idempotency_state_changes,
        planned_state_entries,
        seeded_user_content_text,
        should_seed_stale_graphify_section,
        should_seed_user_content,
        stale_sidecar_seed_plans,
        user_content_seed_plans,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import (  # type: ignore[no-redef]
        InstallSurface,
        SkillSidecarExpectation,
        is_skill_effect,
    )
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
    from install_surface_generated import (  # type: ignore[no-redef]
        GeneratedArtifactCopyPlan,
        GeneratedFileDecision,
        GeneratedFileExpectationLike,
        GeneratedFileObservation,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        is_expected_generated_key,
        is_relevant_generated_file,
        is_skill_sidecar_relative,
        is_small_text_candidate,
        text_mentions_expected_generated_marker,
    )
    from install_surface_statuses import (  # type: ignore[no-redef]
        FileFingerprintObservation,
        InstallSurfaceObservation,
        InstallSurfaceStatus,
        UninstallSurfaceObservation,
        command_hook_present,
        expected_kind_status_from_observation,
        file_fingerprint_from_observation,
        graphify_section_removed,
        hooks_by_event,
        install_surface_kind_status_from_observation,
        installed_surface_status_from_observation,
        json_expectation_status,
        json_marker_status_from_observation,
        json_value_contains_marker,
        plugin_config_present,
        text_marker_status_from_text,
        uninstalled_surface_status_from_observation,
    )
    from install_surface_state import (  # type: ignore[no-redef]
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        IdempotencyStateChange,
        StaleSidecarSeedKind,
        StaleSidecarSeedPlan,
        StateEntryPlan,
        UserContentSeedPlan,
        expected_generated_relative_keys,
        expected_manifest_relatives,
        expects_stale_graphify_section_repaired,
        expects_user_content_preserved,
        idempotency_state_changes,
        planned_state_entries,
        seeded_user_content_text,
        should_seed_stale_graphify_section,
        should_seed_user_content,
        stale_sidecar_seed_plans,
        user_content_seed_plans,
    )


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative
