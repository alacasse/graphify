from __future__ import annotations

try:
    from . import expected_effects
    from . import file_effect_generated_artifacts
    from . import file_effect_oracle
    from . import scenario_file_effects_adapter
    from . import file_effect_sidecars
    from . import file_effect_state
    from . import file_effect_surfaces
    from .install_surface_generated import (
        decide_generated_file_observation as _decide_generated_file_observation,
        generated_artifact_copy_plan as _generated_artifact_copy_plan,
        generated_file_observation as _generated_file_observation,
        is_excluded_generated_path as _is_excluded_generated_path,
        text_mentions_expected_generated_marker as _text_mentions_expected_generated_marker,
    )
except ImportError:
    import expected_effects  # type: ignore[no-redef]
    import file_effect_generated_artifacts  # type: ignore[no-redef]
    import file_effect_oracle  # type: ignore[no-redef]
    import scenario_file_effects_adapter  # type: ignore[no-redef]
    import file_effect_sidecars  # type: ignore[no-redef]
    import file_effect_state  # type: ignore[no-redef]
    import file_effect_surfaces  # type: ignore[no-redef]
    from install_surface_generated import (  # type: ignore[no-redef]
        decide_generated_file_observation as _decide_generated_file_observation,
        generated_artifact_copy_plan as _generated_artifact_copy_plan,
        generated_file_observation as _generated_file_observation,
        is_excluded_generated_path as _is_excluded_generated_path,
        text_mentions_expected_generated_marker as _text_mentions_expected_generated_marker,
    )


STALE_GRAPHIFY_SENTINEL = file_effect_state.STALE_GRAPHIFY_SENTINEL
USER_SENTINEL = file_effect_state.USER_SENTINEL

GENERATED_COPY_EXCLUDES = file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES
pruned_file_walk = file_effect_generated_artifacts.pruned_file_walk
decide_generated_file_observation = _decide_generated_file_observation
generated_artifact_copy_plan = _generated_artifact_copy_plan
generated_file_observation = _generated_file_observation
is_excluded_generated_path = _is_excluded_generated_path
text_mentions_expected_generated_marker = _text_mentions_expected_generated_marker

STALE_SIDECAR_SEED_DETAILS = file_effect_sidecars.STALE_SIDECAR_SEED_DETAILS

# Compatibility import surface: sidecar behavior lives in file_effect_sidecars and
# installer-core topic modules, but older callers imported these names here.
expected_skill_sidecar_relatives = file_effect_sidecars.expected_skill_sidecar_relatives
installed_reference_sidecar_status = file_effect_sidecars.installed_reference_sidecar_status
reference_sidecar_expectation = file_effect_sidecars.reference_sidecar_expectation
references_tmp_absence_status = file_effect_sidecars.references_tmp_absence_status
skill_dir_for_entry = file_effect_sidecars.skill_dir_for_entry
skill_reference_pointer_status = file_effect_sidecars.skill_reference_pointer_status
skill_references_relative = file_effect_sidecars.skill_references_relative
skill_references_tmp_relative = file_effect_sidecars.skill_references_tmp_relative
skill_sidecar_expectation = file_effect_sidecars.skill_sidecar_expectation
skill_version_status = file_effect_sidecars.skill_version_status
skill_version_relative = file_effect_sidecars.skill_version_relative
stale_sidecar_seed_plans = file_effect_sidecars.stale_sidecar_seed_plans
uninstalled_skill_sidecar_status = file_effect_sidecars.uninstalled_skill_sidecar_status

expected_manifest_relatives = file_effect_state.expected_manifest_relatives
core_expected_manifest_relatives = file_effect_state.expected_manifest_relatives
expected_generated_relative_keys = file_effect_state.expected_generated_relative_keys
idempotency_state_changes = file_effect_state.idempotency_state_changes
planned_state_entries = file_effect_state.planned_state_entries
user_content_seed_plans = file_effect_state.user_content_seed_plans
is_skill_effect = expected_effects.is_skill_effect

FileFingerprintObservation = file_effect_surfaces.FileFingerprintObservation
InstallSurfaceObservation = file_effect_surfaces.InstallSurfaceObservation
UninstallSurfaceObservation = file_effect_surfaces.UninstallSurfaceObservation
file_fingerprint_from_observation = file_effect_surfaces.file_fingerprint_from_observation
install_surface_kind_status_from_observation = file_effect_surfaces.install_surface_kind_status_from_observation
installed_surface_status_from_observation = file_effect_surfaces.installed_surface_status_from_observation
is_json_effect = file_effect_surfaces.is_json_effect
uninstalled_surface_status_from_observation = file_effect_surfaces.uninstalled_surface_status_from_observation

check_record = scenario_file_effects_adapter.check_record
ScenarioFileEffectsAdapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter

FileEffectOracle = file_effect_oracle.FileEffectOracle
assert_idempotent_state = file_effect_oracle.assert_idempotent_state
