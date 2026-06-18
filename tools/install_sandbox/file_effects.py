from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from .expected_effects import is_skill_effect
    from . import file_effect_sidecars
    from . import file_effect_surfaces
    from .file_walk import pruned_file_walk
    from .install_surface_core import (
        resolve_install_root,
        resolve_install_surface_path,
    )
    from .install_surface_generated import (
        GeneratedFileDecision,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        text_mentions_expected_generated_marker,
    )
    from .install_surface_state import (
        STALE_GRAPHIFY_SENTINEL as _STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL as _USER_SENTINEL,
        expected_generated_relative_keys,
        expected_manifest_relatives as core_expected_manifest_relatives,
        idempotency_state_changes,
        planned_state_entries,
        user_content_seed_plans,
    )
    from .platform_specs import InstallSurface, Scenario, TextExpectation
    from .reference_resolution import PackagedReferenceResolution
except ImportError:
    from expected_effects import is_skill_effect  # type: ignore[no-redef]
    import file_effect_sidecars  # type: ignore[no-redef]
    import file_effect_surfaces  # type: ignore[no-redef]
    from file_walk import pruned_file_walk
    from install_surface_core import (  # type: ignore[no-redef]
        resolve_install_root,
        resolve_install_surface_path,
    )
    from install_surface_generated import (  # type: ignore[no-redef]
        GeneratedFileDecision,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        text_mentions_expected_generated_marker,
    )
    from install_surface_state import (  # type: ignore[no-redef]
        STALE_GRAPHIFY_SENTINEL as _STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL as _USER_SENTINEL,
        expected_generated_relative_keys,
        expected_manifest_relatives as core_expected_manifest_relatives,
        idempotency_state_changes,
        planned_state_entries,
        user_content_seed_plans,
    )
    from platform_specs import InstallSurface, Scenario, TextExpectation
    from reference_resolution import PackagedReferenceResolution


STALE_GRAPHIFY_SENTINEL = _STALE_GRAPHIFY_SENTINEL
USER_SENTINEL = _USER_SENTINEL

GENERATED_COPY_EXCLUDES = (
    ".local",
    ".cache",
    "__pycache__",
    ".pytest_cache",
)

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

FileFingerprintObservation = file_effect_surfaces.FileFingerprintObservation
InstallSurfaceObservation = file_effect_surfaces.InstallSurfaceObservation
UninstallSurfaceObservation = file_effect_surfaces.UninstallSurfaceObservation
file_fingerprint_from_observation = file_effect_surfaces.file_fingerprint_from_observation
install_surface_kind_status_from_observation = file_effect_surfaces.install_surface_kind_status_from_observation
installed_surface_status_from_observation = file_effect_surfaces.installed_surface_status_from_observation
is_json_effect = file_effect_surfaces.is_json_effect
uninstalled_surface_status_from_observation = file_effect_surfaces.uninstalled_surface_status_from_observation


def check_record(path: Path | str, ok: bool, detail: str, *, root: str | None = None, relative: str | Path | None = None, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


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
        return core_expected_manifest_relatives(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
            root_name,
        )

    def seed_user_owned_content(self, scenario: Scenario) -> None:
        for plan in user_content_seed_plans(scenario.expected):
            path = self.root_path(plan.root_name) / plan.relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plan.text, encoding="utf-8")

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
        yield from pruned_file_walk(base, self.manifest_prune_dirs)

    def assert_no_unexpected_graphify_files(
        self,
        scenario: Scenario,
        *,
        phase: str,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        expected = (
            expected_generated_relative_keys(
                scenario.expected,
                self.packaged_reference_resolution(scenario.platform),
            )
            if expected_keys is None
            else expected_keys
        )
        checks: list[dict[str, object]] = []
        for root_name, root in self.roots.items():
            if not root.exists():
                continue
            for path in self.pruned_file_walk(root):
                relative = path.relative_to(root)
                rel = relative.as_posix()
                decision = self.generated_file_decision(
                    scenario,
                    root_name,
                    relative,
                    path,
                    apply_excludes=True,
                    expected_keys=expected,
                )
                if decision.observation.expected_key:
                    continue
                if not decision.should_include:
                    continue
                checks.append(
                    check_record(
                        path,
                        False,
                        f"unexpected_graphify_related_file_after_{phase}",
                        root=root_name,
                        relative=rel,
                    )
                )
        if not checks:
            checks.append(check_record("unexpected-graphify-files", True, f"none_after_{phase}"))
        return checks

    def assert_scope_boundaries(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_scope_boundaries(scenario, self.roots)

    def file_fingerprint(self, path: Path, marker: str | None = None, text_expectation: TextExpectation | None = None) -> dict[str, object]:
        return file_effect_surfaces.file_fingerprint(path, marker, text_expectation)

    # Idempotency state
    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        state: dict[str, dict[str, object]] = {}
        installed_reference_relatives = {
            (entry.root, entry.relative): self.installed_skill_reference_relatives(entry)
            for entry in scenario.expected
            if is_skill_effect(entry)
        }
        plan = planned_state_entries(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
            installed_skill_reference_relatives=installed_reference_relatives,
        )
        for entry in plan:
            state[entry.key] = self.file_fingerprint(
                self.root_path(entry.root_name) / entry.relative,
                entry.marker,
                entry.text_expectation,
            )
        return state

    def file_mentions_expected_generated_marker(self, scenario: Scenario, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return text_mentions_expected_generated_marker(scenario.generated_file_expectation, text)

    def generated_file_size(self, path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

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
        excluded_path = apply_excludes and is_excluded_generated_path(relative, GENERATED_COPY_EXCLUDES)
        size = None if excluded_path else self.generated_file_size(path)
        observation = generated_file_observation(
            scenario.generated_file_expectation,
            scenario.expected,
            root_name,
            relative,
            file_size=size,
            mentions_expected_marker=False,
            excluded_path=excluded_path,
            expected_keys=expected_keys,
        )
        if observation.needs_text_marker_match:
            observation = generated_file_observation(
                scenario.generated_file_expectation,
                scenario.expected,
                root_name,
                relative,
                file_size=size,
                mentions_expected_marker=self.file_mentions_expected_generated_marker(scenario, path),
                excluded_path=excluded_path,
                expected_keys=expected_keys,
            )
        return decide_generated_file_observation(observation)

    def is_relevant_generated_file(self, scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
        return self.generated_file_decision(scenario, root_name, relative, path, apply_excludes=False).is_relevant

    def copy_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        out = artifact_dir / "generated-files"
        if out.exists():
            shutil.rmtree(out)
        expected_keys = expected_generated_relative_keys(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
        )
        for root_name, root in self.roots.items():
            if not root.exists():
                continue
            for path in self.pruned_file_walk(root):
                rel = path.relative_to(root)
                if not self.generated_file_decision(
                    scenario,
                    root_name,
                    rel,
                    path,
                    apply_excludes=True,
                    expected_keys=expected_keys,
                ).should_include:
                    continue
                plan = generated_artifact_copy_plan(root_name, rel)
                dest = out / plan.destination_relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)


def assert_idempotent_state(before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for change in idempotency_state_changes(before, after):
        checks.append(
            check_record(
                change.key,
                change.stable,
                "unchanged_after_repeat_install" if change.stable else "changed_after_repeat_install",
            )
        )
    return checks


def _universal_uninstall_adapter_checks(
    install_checks: Iterable[dict[str, object]],
    uninstall_checks: Iterable[dict[str, object]],
    unexpected_checks: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    return [*install_checks, *uninstall_checks, *unexpected_checks]


@dataclass(frozen=True)
class ScenarioFileEffectsAdapter:
    oracle: FileEffectOracle
    write_file_manifest: Callable[..., None]
    run_equivalence_check: Callable[[Scenario, dict[str, str], Path], list[dict[str, object]]]

    def seed_scenario_inputs(self, scenario: Scenario) -> None:
        self.oracle.seed_user_owned_content(scenario)

    def write_manifest(self, path: Path, roots: dict[str, Path], **kwargs: object) -> None:
        self.write_file_manifest(path, roots, **kwargs)

    def capture_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        return self.oracle.scenario_file_state(scenario)

    def install_checks(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.oracle.assert_expected_files(scenario) + self.oracle.assert_scope_boundaries(scenario)

    def unexpected_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def archive_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        self.oracle.copy_generated_files(scenario, artifact_dir)

    def repeat_install_checks(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> list[dict[str, object]]:
        return assert_idempotent_state(before, after) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def seed_stale_sidecar_repair(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.oracle.seed_stale_skill_sidecars(scenario)

    def stale_sidecar_repair_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_installed_skill_sidecars(scenario) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def uninstall_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_uninstalled(scenario) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def equivalence_checks(self, scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]:
        return self.run_equivalence_check(scenario, env, artifact_dir)

    def universal_uninstall_checks(
        self,
        runner_scenario: Scenario,
        installed_scenarios: Iterable[Scenario],
        install_checks: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        scenarios = list(installed_scenarios)
        expected_keys: set[tuple[str, str]] = set()
        for scenario in scenarios:
            expected_keys.update(
                expected_generated_relative_keys(
                    scenario.expected,
                    self.oracle.packaged_reference_resolution(scenario.platform),
                )
            )
        uninstall_checks: list[dict[str, object]] = []
        for scenario in scenarios:
            uninstall_checks.extend(self.oracle.assert_uninstalled(scenario))
        unexpected_checks = self.oracle.assert_no_unexpected_graphify_files(
            runner_scenario,
            phase="universal_uninstall",
            expected_keys=expected_keys,
        )
        return _universal_uninstall_adapter_checks(
            install_checks,
            uninstall_checks,
            unexpected_checks,
        )

    def disposable_artifact_checks(self, disposable_path: Path, removed: bool) -> list[dict[str, object]]:
        return [check_record(disposable_path, removed, "removed" if removed else "still_exists")]

    def purge_checks(self, graphify_out: Path, purged: bool) -> list[dict[str, object]]:
        checks = self.disposable_artifact_checks(graphify_out, purged)
        for check in checks:
            if check["detail"] == "removed":
                check["detail"] = "purged"
        return checks
