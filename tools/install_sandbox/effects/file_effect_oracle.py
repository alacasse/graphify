from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import file_effect_generated_artifacts
from . import file_effect_sidecars
from . import file_effect_state
from . import file_effect_surfaces
from ..surfaces.install_surface_generated import GeneratedFileDecision
from ..surfaces.install_surface_models import TextExpectation
from ..surfaces.path_resolution import resolve_install_root
from ..targets.reference_resolution import PackagedReferenceResolution
from ..targets.install_target_models import Scenario


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

    # Skill sidecar checks
    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_sidecars.seed_stale_skill_sidecars(
            scenario,
            self.roots,
            self.packaged_reference_resolution,
        )

    def expected_manifest_relatives(self, scenario: Scenario, root_name: str) -> set[Path]:
        return file_effect_state.expected_manifest_relatives(
            scenario.expected,
            self.packaged_reference_resolution(scenario.target_name),
            root_name,
        )

    def seed_user_owned_content(self, scenario: Scenario) -> None:
        return file_effect_state.seed_user_owned_content(scenario, self.root_path)

    # Install/uninstall assertions
    def assert_expected_files(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_expected_files(
            scenario,
            self.roots,
            lambda checked_scenario, entry: file_effect_sidecars.assert_installed_skill_sidecar(
                checked_scenario,
                entry,
                self.roots,
                self.packaged_reference_resolution,
                self.expected_graphify_version,
            ),
        )

    def assert_uninstalled(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_uninstalled(
            scenario,
            self.roots,
            lambda entry: file_effect_sidecars.uninstalled_skill_sidecar_checks(entry, self.roots),
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
            lambda entry: file_effect_sidecars.installed_skill_reference_relatives(entry, self.roots),
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
