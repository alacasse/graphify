from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from . import expected_effects
    from . import file_effect_generated_artifacts
    from . import scenario_file_effects_adapter
    from . import file_effect_sidecars
    from . import file_effect_state
    from . import file_effect_surfaces
    from .install_surface_core import (
        resolve_install_root,
        resolve_install_surface_path,
    )
    from .install_surface_generated import (
        GeneratedFileDecision,
        decide_generated_file_observation as _decide_generated_file_observation,
        generated_artifact_copy_plan as _generated_artifact_copy_plan,
        generated_file_observation as _generated_file_observation,
        is_excluded_generated_path as _is_excluded_generated_path,
        text_mentions_expected_generated_marker as _text_mentions_expected_generated_marker,
    )
    from .platform_specs import InstallSurface, Scenario, TextExpectation
    from .reference_resolution import PackagedReferenceResolution
except ImportError:
    import expected_effects  # type: ignore[no-redef]
    import file_effect_generated_artifacts  # type: ignore[no-redef]
    import scenario_file_effects_adapter  # type: ignore[no-redef]
    import file_effect_sidecars  # type: ignore[no-redef]
    import file_effect_state  # type: ignore[no-redef]
    import file_effect_surfaces  # type: ignore[no-redef]
    from install_surface_core import (  # type: ignore[no-redef]
        resolve_install_root,
        resolve_install_surface_path,
    )
    from install_surface_generated import (  # type: ignore[no-redef]
        GeneratedFileDecision,
        decide_generated_file_observation as _decide_generated_file_observation,
        generated_artifact_copy_plan as _generated_artifact_copy_plan,
        generated_file_observation as _generated_file_observation,
        is_excluded_generated_path as _is_excluded_generated_path,
        text_mentions_expected_generated_marker as _text_mentions_expected_generated_marker,
    )
    from platform_specs import InstallSurface, Scenario, TextExpectation
    from reference_resolution import PackagedReferenceResolution


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


@dataclass(frozen=True)
class FileEffectOracle:
    roots: dict[str, Path]
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution]
    expected_graphify_version: Callable[[], str]
    manifest_prune_dirs: set[str]

    # Path helpers
    def root_path(self, root: str) -> Path:
        return resolve_install_root(root, self.roots)

    def expected_path(self, entry: InstallSurface) -> Path:
        return resolve_install_surface_path(entry, self.roots)

    def skill_assertion_record(self, entry: InstallSurface, relative: Path, ok: bool, detail: str) -> dict[str, object]:
        return file_effect_sidecars.skill_assertion_record(entry, self.roots, relative, ok, detail)

    def installed_skill_reference_relatives(self, entry: InstallSurface) -> set[Path]:
        return file_effect_sidecars.installed_skill_reference_relatives(entry, self.roots)

    def tracked_skill_sidecar_relatives(self, scenario: Scenario, entry: InstallSurface) -> set[Path]:
        return file_effect_sidecars.tracked_skill_sidecar_relatives(
            scenario,
            entry,
            self.roots,
            self.packaged_reference_resolution,
        )

    def installed_reference_names(self, refs_dir: Path) -> list[str]:
        return file_effect_sidecars.installed_reference_names(refs_dir)

    # Skill sidecar checks
    def check_skill_version(self, entry: InstallSurface) -> dict[str, object]:
        return file_effect_sidecars.check_skill_version(entry, self.roots, self.expected_graphify_version)

    def check_references_tmp_absent(self, entry: InstallSurface) -> dict[str, object]:
        return file_effect_sidecars.check_references_tmp_absent(entry, self.roots)

    def check_packaged_references(self, scenario: Scenario, entry: InstallSurface) -> dict[str, object]:
        return file_effect_sidecars.check_packaged_references(
            scenario,
            entry,
            self.roots,
            self.packaged_reference_resolution,
        )

    def check_skill_reference_pointers(self, entry: InstallSurface, skill_text: str) -> dict[str, object]:
        return file_effect_sidecars.check_skill_reference_pointers(
            entry,
            self.roots,
            skill_text,
        )

    def assert_installed_skill_sidecar(self, scenario: Scenario, entry: InstallSurface) -> list[dict[str, object]]:
        return file_effect_sidecars.assert_installed_skill_sidecar(
            scenario,
            entry,
            self.roots,
            self.packaged_reference_resolution,
            self.expected_graphify_version,
        )

    def assert_installed_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_sidecars.assert_installed_skill_sidecars(
            scenario,
            self.roots,
            self.packaged_reference_resolution,
            self.expected_graphify_version,
        )

    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_sidecars.seed_stale_skill_sidecars(
            scenario,
            self.roots,
            self.packaged_reference_resolution,
        )

    def expected_manifest_relatives(self, scenario: Scenario, root_name: str) -> set[Path]:
        return file_effect_state.expected_manifest_relatives(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
            root_name,
        )

    def seed_user_owned_content(self, scenario: Scenario) -> None:
        return file_effect_state.seed_user_owned_content(scenario, self.root_path)

    def installed_surface_observation(self, entry: InstallSurface) -> InstallSurfaceObservation:
        return file_effect_surfaces.installed_surface_observation(entry, self.roots)

    def expected_entry_status(self, entry: InstallSurface) -> tuple[bool, str]:
        observation = self.installed_surface_observation(entry)
        return file_effect_surfaces.expected_entry_status_from_observation(entry, observation)

    # Install/uninstall assertions
    def assert_expected_files(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_expected_files(
            scenario,
            self.roots,
            self.assert_installed_skill_sidecar,
            self.expected_entry_status,
        )

    def uninstalled_surface_observation(self, entry: InstallSurface) -> UninstallSurfaceObservation:
        return file_effect_surfaces.uninstalled_surface_observation(entry, self.roots)

    def uninstalled_entry_status(self, entry: InstallSurface) -> tuple[bool, str]:
        observation = self.uninstalled_surface_observation(entry)
        return file_effect_surfaces.uninstalled_entry_status_from_observation(entry, observation)

    def uninstalled_skill_sidecar_checks(self, entry: InstallSurface) -> list[dict[str, object]]:
        return file_effect_sidecars.uninstalled_skill_sidecar_checks(entry, self.roots)

    def assert_uninstalled(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_uninstalled(
            scenario,
            self.roots,
            self.uninstalled_skill_sidecar_checks,
            self.uninstalled_entry_status,
        )

    # Generated-file discovery/copying
    def pruned_file_walk(self, base: Path) -> Iterable[Path]:
        yield from file_effect_generated_artifacts.pruned_file_walk(base, self.manifest_prune_dirs)

    def assert_no_unexpected_graphify_files(
        self,
        scenario: Scenario,
        *,
        phase: str,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        return file_effect_generated_artifacts.assert_no_unexpected_graphify_files(
            scenario,
            self.roots,
            self.packaged_reference_resolution,
            phase=phase,
            expected_keys=expected_keys,
            pruned_file_walk_for=self.pruned_file_walk,
            generated_file_decision_for=self.generated_file_decision,
        )

    def assert_scope_boundaries(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_scope_boundaries(scenario, self.roots)

    def file_fingerprint(self, path: Path, marker: str | None = None, text_expectation: TextExpectation | None = None) -> dict[str, object]:
        return file_effect_surfaces.file_fingerprint(path, marker, text_expectation)

    # Idempotency state
    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        return file_effect_state.scenario_file_state(
            scenario,
            self.packaged_reference_resolution,
            self.root_path,
            self.installed_skill_reference_relatives,
            self.file_fingerprint,
        )

    def file_mentions_expected_generated_marker(self, scenario: Scenario, path: Path) -> bool:
        return file_effect_generated_artifacts.file_mentions_expected_generated_marker(scenario, path)

    def generated_file_size(self, path: Path) -> int | None:
        return file_effect_generated_artifacts.generated_file_size(path)

    def generated_file_decision(
        self,
        scenario: Scenario,
        root_name: str,
        relative: Path,
        path: Path,
        *,
        apply_excludes: bool,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> GeneratedFileDecision:
        return file_effect_generated_artifacts.generated_file_decision(
            scenario,
            root_name,
            relative,
            path,
            apply_excludes=apply_excludes,
            generated_copy_excludes=GENERATED_COPY_EXCLUDES,
            expected_keys=expected_keys,
            size_for_path=self.generated_file_size,
            marker_match_for_path=self.file_mentions_expected_generated_marker,
        )

    def is_relevant_generated_file(self, scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
        return file_effect_generated_artifacts.is_relevant_generated_file(
            scenario,
            root_name,
            relative,
            path,
            self.generated_file_decision,
        )

    def copy_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        file_effect_generated_artifacts.copy_generated_files(
            scenario,
            self.roots,
            self.packaged_reference_resolution,
            artifact_dir,
            pruned_file_walk_for=self.pruned_file_walk,
            generated_file_decision_for=self.generated_file_decision,
        )


def assert_idempotent_state(before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return file_effect_state.assert_idempotent_state(before, after)
