from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from . import file_effect_generated_artifacts
    from . import file_effect_sidecars
    from . import file_effect_state
    from . import file_effect_surfaces
    from ..surfaces.path_resolution import (
        resolve_install_root,
        resolve_install_surface_path,
    )
    from ..surfaces.install_surface_generated import GeneratedFileDecision
    from ..platform_specs import InstallSurface, Scenario, TextExpectation
    from ..reference_resolution import PackagedReferenceResolution
except ImportError:  # pragma: no cover - direct script import fallback
    try:
        from effects import file_effect_generated_artifacts  # type: ignore[no-redef]
        from effects import file_effect_sidecars  # type: ignore[no-redef]
        from effects import file_effect_state  # type: ignore[no-redef]
        from effects import file_effect_surfaces  # type: ignore[no-redef]
    except ImportError:
        import file_effect_generated_artifacts  # type: ignore[no-redef]
        import file_effect_sidecars  # type: ignore[no-redef]
        import file_effect_state  # type: ignore[no-redef]
        import file_effect_surfaces  # type: ignore[no-redef]
    from surfaces.path_resolution import (  # type: ignore[no-redef]
        resolve_install_root,
        resolve_install_surface_path,
    )
    from surfaces.install_surface_generated import GeneratedFileDecision  # type: ignore[no-redef]
    from platform_specs import InstallSurface, Scenario, TextExpectation  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution  # type: ignore[no-redef]


GENERATED_COPY_EXCLUDES = file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES


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

    def installed_surface_observation(self, entry: InstallSurface) -> file_effect_surfaces.InstallSurfaceObservation:
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

    def uninstalled_surface_observation(self, entry: InstallSurface) -> file_effect_surfaces.UninstallSurfaceObservation:
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

    def file_fingerprint(
        self,
        path: Path,
        marker: str | None = None,
        text_expectation: TextExpectation | None = None,
    ) -> dict[str, object]:
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
