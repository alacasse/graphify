from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from .expected_effects import is_json_effect, is_skill_effect
    from .file_walk import pruned_file_walk
    from .install_surface_core import (
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        FileFingerprintObservation,
        InstallSurfaceObservation,
        UninstallSurfaceObservation,
        ReferenceSidecarExpectation,
        GeneratedFileDecision,
        command_hook_present,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        expected_kind_status,
        expected_manifest_relatives as core_expected_manifest_relatives,
        expected_generated_relative_keys,
        expected_skill_sidecar_relatives,
        file_fingerprint_from_observation,
        generated_file_observation,
        graphify_section_removed,
        hooks_by_event,
        idempotency_state_changes,
        install_surface_kind_status_from_observation,
        is_excluded_generated_path,
        is_expected_generated_key,
        is_skill_sidecar_relative,
        is_small_text_candidate,
        installed_reference_sidecar_status,
        installed_surface_status_from_observation,
        json_expectation_status,
        json_value_contains_marker,
        planned_state_entries,
        plugin_config_present,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        resolve_install_root,
        resolve_install_surface_path,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_reference_pointers,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_relative_dir,
        skill_sidecar_expectation,
        skill_version_status,
        skill_version_relative,
        seeded_user_content_text,
        should_seed_stale_graphify_section,
        should_seed_user_content,
        stale_sidecar_seed_plans,
        text_mentions_expected_generated_marker,
        uninstalled_skill_sidecar_status,
        uninstalled_surface_status_from_observation,
        user_content_seed_plans,
    )
    from .platform_specs import InstallSurface, JsonExpectation, JsonHookExpectation, JsonPluginExpectation, Scenario, SkillSidecarExpectation, TextExpectation
    from .reference_resolution import PackagedReferenceResolution
except ImportError:
    from expected_effects import is_json_effect, is_skill_effect  # type: ignore[no-redef]
    from file_walk import pruned_file_walk
    from install_surface_core import (  # type: ignore[no-redef]
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        FileFingerprintObservation,
        InstallSurfaceObservation,
        UninstallSurfaceObservation,
        ReferenceSidecarExpectation,
        GeneratedFileDecision,
        command_hook_present,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        expected_kind_status,
        expected_manifest_relatives as core_expected_manifest_relatives,
        expected_generated_relative_keys,
        expected_skill_sidecar_relatives,
        file_fingerprint_from_observation,
        generated_file_observation,
        graphify_section_removed,
        hooks_by_event,
        idempotency_state_changes,
        install_surface_kind_status_from_observation,
        is_excluded_generated_path,
        is_expected_generated_key,
        is_skill_sidecar_relative,
        is_small_text_candidate,
        installed_reference_sidecar_status,
        installed_surface_status_from_observation,
        json_expectation_status,
        json_value_contains_marker,
        planned_state_entries,
        plugin_config_present,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        resolve_install_root,
        resolve_install_surface_path,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_reference_pointers,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_relative_dir,
        skill_sidecar_expectation,
        skill_version_status,
        skill_version_relative,
        seeded_user_content_text,
        should_seed_stale_graphify_section,
        should_seed_user_content,
        stale_sidecar_seed_plans,
        text_mentions_expected_generated_marker,
        uninstalled_skill_sidecar_status,
        uninstalled_surface_status_from_observation,
        user_content_seed_plans,
    )
    from platform_specs import InstallSurface, JsonExpectation, JsonHookExpectation, JsonPluginExpectation, Scenario, SkillSidecarExpectation, TextExpectation
    from reference_resolution import PackagedReferenceResolution


GENERATED_COPY_EXCLUDES = (
    ".local",
    ".cache",
    "__pycache__",
    ".pytest_cache",
)

STALE_SIDECAR_SEED_DETAILS = {
    "stale_reference_fragment": "seeded_stale_reference_fragment",
    "staged_reference_fragment": "seeded_staged_reference_fragment",
}


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

    def is_skill_expected(self, entry: InstallSurface) -> bool:
        return is_skill_effect(entry)

    def skill_sidecar_expectation(self, entry: InstallSurface) -> SkillSidecarExpectation:
        return skill_sidecar_expectation(entry)

    def skill_dir_for_entry(self, entry: InstallSurface) -> Path:
        return skill_dir_for_entry(entry, self.roots)

    def skill_relative_dir(self, entry: InstallSurface) -> Path:
        return skill_relative_dir(entry)

    def skill_assertion_record(self, entry: InstallSurface, relative: Path, ok: bool, detail: str) -> dict[str, object]:
        return check_record(self.root_path(entry.root) / relative, ok, detail, root=entry.root, relative=relative)

    def skill_version_relative(self, entry: InstallSurface) -> Path:
        return skill_version_relative(entry)

    def skill_references_relative(self, entry: InstallSurface) -> Path:
        return skill_references_relative(entry)

    def skill_references_tmp_relative(self, entry: InstallSurface) -> Path:
        return skill_references_tmp_relative(entry)

    def expected_skill_sidecar_relatives(self, scenario: Scenario, entry: InstallSurface) -> set[Path]:
        return expected_skill_sidecar_relatives(entry, self.packaged_reference_resolution(scenario.platform))

    def installed_skill_reference_relatives(self, entry: InstallSurface) -> set[Path]:
        refs_dir = self.skill_dir_for_entry(entry) / self.skill_sidecar_expectation(entry).references_dir
        refs_relative = self.skill_references_relative(entry)
        if not refs_dir.is_dir():
            return set()
        return {refs_relative / path.name for path in refs_dir.glob("*.md") if path.is_file()}

    def tracked_skill_sidecar_relatives(self, scenario: Scenario, entry: InstallSurface) -> set[Path]:
        return self.expected_skill_sidecar_relatives(scenario, entry) | self.installed_skill_reference_relatives(entry)

    def reference_sidecar_expectation(self, scenario: Scenario) -> ReferenceSidecarExpectation:
        return reference_sidecar_expectation(self.packaged_reference_resolution(scenario.platform))

    def installed_reference_names(self, refs_dir: Path) -> list[str]:
        if not refs_dir.is_dir():
            return []
        return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())

    def skill_reference_pointers(self, entry: InstallSurface, skill_text: str) -> list[str]:
        return skill_reference_pointers(self.skill_sidecar_expectation(entry), skill_text)

    # Skill sidecar checks
    def check_skill_version(self, entry: InstallSurface) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        version_path = skill_dir / self.skill_sidecar_expectation(entry).version_name
        version_relative = self.skill_version_relative(entry)
        expected_version = self.expected_graphify_version()
        version_text = version_path.read_text(encoding="utf-8", errors="replace") if version_path.exists() else None
        version_ok, version_detail = skill_version_status(version_text, expected_version)
        return self.skill_assertion_record(entry, version_relative, version_ok, version_detail)

    def check_references_tmp_absent(self, entry: InstallSurface) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        refs_tmp = skill_dir / self.skill_sidecar_expectation(entry).references_tmp_dir
        tmp_ok, tmp_detail = references_tmp_absence_status(refs_tmp.exists())
        return self.skill_assertion_record(
            entry,
            self.skill_references_tmp_relative(entry),
            tmp_ok,
            tmp_detail,
        )

    def check_packaged_references(self, scenario: Scenario, entry: InstallSurface) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        refs_dir = skill_dir / self.skill_sidecar_expectation(entry).references_dir
        refs_relative = self.skill_references_relative(entry)
        expectation = self.reference_sidecar_expectation(scenario)
        refs_ok, refs_detail = installed_reference_sidecar_status(
            expectation,
            references_exists=refs_dir.exists(),
            references_is_dir=refs_dir.is_dir(),
            installed_names=self.installed_reference_names(refs_dir),
        )
        return self.skill_assertion_record(entry, refs_relative, refs_ok, refs_detail)

    def check_skill_reference_pointers(self, entry: InstallSurface, skill_text: str) -> dict[str, object]:
        sidecar = self.skill_sidecar_expectation(entry)
        refs_dir = self.skill_dir_for_entry(entry) / sidecar.references_dir
        pointer_ok, pointer_detail = skill_reference_pointer_status(
            sidecar,
            skill_text,
            references_is_dir=refs_dir.is_dir(),
            installed_names=self.installed_reference_names(refs_dir),
        )
        return self.skill_assertion_record(entry, Path(entry.relative), pointer_ok, pointer_detail)

    def assert_installed_skill_sidecar(self, scenario: Scenario, entry: InstallSurface) -> list[dict[str, object]]:
        if not self.is_skill_expected(entry):
            return []

        skill_path = self.expected_path(entry)
        skill_text = skill_path.read_text(encoding="utf-8", errors="replace") if skill_path.is_file() else ""
        return [
            self.check_skill_version(entry),
            self.check_references_tmp_absent(entry),
            self.check_packaged_references(scenario, entry),
            self.check_skill_reference_pointers(entry, skill_text),
        ]

    def assert_installed_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            checks.extend(self.assert_installed_skill_sidecar(scenario, entry))
        return checks

    def progressive_skill_entries(self, scenario: Scenario) -> list[InstallSurface]:
        resolution = self.packaged_reference_resolution(scenario.platform)
        return [
            entry
            for entry in scenario.expected
            if stale_sidecar_seed_plans((entry,), resolution)
        ]

    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        seeded: list[dict[str, object]] = []
        plans = stale_sidecar_seed_plans(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
        )
        for plan in plans:
            path = self.root_path(plan.root_name) / plan.relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plan.text, encoding="utf-8")
            seeded.append(
                check_record(
                    path,
                    True,
                    STALE_SIDECAR_SEED_DETAILS[plan.kind],
                    root=plan.root_name,
                    relative=plan.relative,
                )
            )
        return seeded

    def expected_manifest_relatives(self, scenario: Scenario, root_name: str) -> set[Path]:
        return core_expected_manifest_relatives(
            scenario.expected,
            self.packaged_reference_resolution(scenario.platform),
            root_name,
        )

    # User content seeding
    def should_seed_user_content(self, entry: InstallSurface) -> bool:
        return should_seed_user_content(entry)

    def should_seed_stale_graphify_section(self, entry: InstallSurface) -> bool:
        return should_seed_stale_graphify_section(entry)

    def seeded_text(self, entry: InstallSurface) -> str:
        return seeded_user_content_text(entry)

    def seed_user_owned_content(self, scenario: Scenario) -> None:
        for plan in user_content_seed_plans(scenario.expected):
            path = self.root_path(plan.root_name) / plan.relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plan.text, encoding="utf-8")

    def installed_surface_observation(self, entry: InstallSurface) -> InstallSurfaceObservation:
        path = self.expected_path(entry)
        base = InstallSurfaceObservation(
            path=path,
            exists=path.exists(),
            is_file=path.is_file(),
            is_dir=path.is_dir(),
        )
        status = install_surface_kind_status_from_observation(entry, base)
        if not status.ok or not entry.marker:
            return base
        if is_json_effect(entry):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return InstallSurfaceObservation(
                    path=path,
                    exists=base.exists,
                    is_file=base.is_file,
                    is_dir=base.is_dir,
                    json_error_detail=f"invalid_json={exc.msg}",
                )
            except OSError as exc:
                return InstallSurfaceObservation(
                    path=path,
                    exists=base.exists,
                    is_file=base.is_file,
                    is_dir=base.is_dir,
                    json_error_detail=f"json_read_failed={exc}",
                )
            return InstallSurfaceObservation(
                path=path,
                exists=base.exists,
                is_file=base.is_file,
                is_dir=base.is_dir,
                json_data=data,
                json_loaded=True,
            )
        return InstallSurfaceObservation(
            path=path,
            exists=base.exists,
            is_file=base.is_file,
            is_dir=base.is_dir,
            text=path.read_text(encoding="utf-8", errors="replace"),
        )

    def expected_entry_status(self, entry: InstallSurface) -> tuple[bool, str]:
        status = installed_surface_status_from_observation(entry, self.installed_surface_observation(entry))
        return status.ok, status.detail

    # Install/uninstall assertions
    def assert_expected_files(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            path = self.expected_path(entry)
            ok, detail = self.expected_entry_status(entry)
            checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
            checks.extend(self.assert_installed_skill_sidecar(scenario, entry))
        return checks

    def uninstalled_surface_observation(self, entry: InstallSurface) -> UninstallSurfaceObservation:
        path = self.expected_path(entry)
        base = UninstallSurfaceObservation(
            path=path,
            exists=path.exists(),
            is_file=path.is_file(),
            is_dir=path.is_dir(),
        )
        text_expectation = entry.text_expectation
        if entry.marker and text_expectation.require_user_content_on_uninstall:
            if not (base.exists and base.is_file):
                return base
        elif not (entry.marker and text_expectation.remove_graphify_section_on_uninstall and base.exists):
            return base
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return UninstallSurfaceObservation(
                path=path,
                exists=base.exists,
                is_file=base.is_file,
                is_dir=base.is_dir,
                text_error_detail=f"text_read_failed={exc}",
            )
        return UninstallSurfaceObservation(
            path=path,
            exists=base.exists,
            is_file=base.is_file,
            is_dir=base.is_dir,
            text=text,
        )

    def uninstalled_entry_status(self, entry: InstallSurface) -> tuple[bool, str]:
        status = uninstalled_surface_status_from_observation(entry, self.uninstalled_surface_observation(entry))
        return status.ok, status.detail

    def graphify_section_removed(self, text: str, entry: InstallSurface) -> bool:
        return graphify_section_removed(text, entry)

    def uninstalled_skill_sidecar_checks(self, entry: InstallSurface) -> list[dict[str, object]]:
        if not self.is_skill_expected(entry):
            return []
        checks: list[dict[str, object]] = []
        for relative in (self.skill_version_relative(entry), self.skill_references_relative(entry), self.skill_references_tmp_relative(entry)):
            sidecar_path = self.root_path(entry.root) / relative
            sidecar_ok, sidecar_detail = uninstalled_skill_sidecar_status(sidecar_path.exists())
            checks.append(
                check_record(
                    sidecar_path,
                    sidecar_ok,
                    sidecar_detail,
                    root=entry.root,
                    relative=relative,
                )
            )
        return checks

    def assert_uninstalled(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            path = self.expected_path(entry)
            if not entry.remove_on_uninstall:
                continue
            ok, detail = self.uninstalled_entry_status(entry)
            checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
            checks.extend(self.uninstalled_skill_sidecar_checks(entry))
        return checks

    def expected_generated_relative_keys(self, scenario: Scenario) -> set[tuple[str, str]]:
        return expected_generated_relative_keys(scenario.expected, self.packaged_reference_resolution(scenario.platform))

    def expected_generated_relative_keys_for_scenarios(self, scenarios: Iterable[Scenario]) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for scenario in scenarios:
            keys.update(self.expected_generated_relative_keys(scenario))
        return keys

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
        expected = self.expected_generated_relative_keys(scenario) if expected_keys is None else expected_keys
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
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            allowed = not scenario.allowed_roots or entry.root in scenario.allowed_roots
            checks.append(check_record(self.expected_path(entry), allowed, "allowed_root" if allowed else "unexpected_root"))
        return checks

    def file_fingerprint(self, path: Path, marker: str | None = None, text_expectation: TextExpectation | None = None) -> dict[str, object]:
        if not path.exists():
            observation = FileFingerprintObservation(exists=False)
        elif path.is_dir():
            observation = FileFingerprintObservation(exists=True, kind="dir")
        else:
            data = path.read_bytes()
            observation = FileFingerprintObservation(
                exists=True,
                kind="file",
                data=data,
                text=data.decode("utf-8", errors="replace") if marker else None,
            )
        return file_fingerprint_from_observation(observation, marker, text_expectation)

    # Idempotency state
    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        state: dict[str, dict[str, object]] = {}
        installed_reference_relatives = {
            (entry.root, entry.relative): self.installed_skill_reference_relatives(entry)
            for entry in scenario.expected
            if self.is_skill_expected(entry)
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

    def should_exclude_generated_path(self, relative: Path) -> bool:
        return is_excluded_generated_path(relative, GENERATED_COPY_EXCLUDES)

    def is_expected_generated_key(self, scenario: Scenario, root_name: str, relative: Path) -> bool:
        return is_expected_generated_key(scenario.expected, root_name, relative)

    def is_skill_sidecar_relative(self, scenario: Scenario, root_name: str, relative: Path) -> bool:
        return is_skill_sidecar_relative(scenario.expected, root_name, relative)

    def is_small_text_candidate(self, scenario: Scenario, path: Path) -> bool:
        size = self.generated_file_size(path)
        return size is not None and is_small_text_candidate(scenario.generated_file_expectation, file_size=size, suffix=path.suffix)

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
        excluded_path = apply_excludes and self.should_exclude_generated_path(relative)
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
        expected_keys = self.expected_generated_relative_keys(scenario)
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
        expected_keys = self.oracle.expected_generated_relative_keys_for_scenarios(scenarios)
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
