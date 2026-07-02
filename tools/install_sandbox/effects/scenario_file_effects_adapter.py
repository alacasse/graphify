from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol

from . import file_effect_generated_artifacts
from . import file_effect_sidecars
from . import file_effect_state
from . import file_effect_surfaces
from ..surfaces.install_surface_generated import GeneratedFileDecision
from ..surfaces.install_surface_models import InstallSurface
from ..targets.install_target_models import Scenario


def check_record(
    path: Path | str,
    ok: bool,
    detail: str,
    *,
    root: str | None = None,
    relative: str | Path | None = None,
    **extra: object,
) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


def _universal_uninstall_adapter_checks(
    install_checks: Iterable[dict[str, object]],
    uninstall_checks: Iterable[dict[str, object]],
    unexpected_checks: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    return [*install_checks, *uninstall_checks, *unexpected_checks]


class ScenarioFileEffectsOracle(Protocol):
    roots: Mapping[str, Path]
    packaged_reference_resolution: Callable[[str], object]
    expected_graphify_version: Callable[[], str]

    def seed_user_owned_content(self, scenario: Scenario) -> None: ...

    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]: ...

    def pruned_file_walk(self, base: Path) -> Iterable[Path]: ...

    def generated_file_decision(
        self,
        scenario: Scenario,
        root_name: str,
        relative: Path,
        path: Path,
        *,
        apply_excludes: bool,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> GeneratedFileDecision: ...

    def copy_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None: ...

    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class InitialInstallFileEffects:
    state_after_install: dict[str, dict[str, object]]
    install_checks: list[dict[str, object]]
    scope_checks: list[dict[str, object]]
    unexpected_install_checks: list[dict[str, object]]


@dataclass(frozen=True)
class RepeatInstallFileEffects:
    state_after_repeat: dict[str, dict[str, object]]
    idempotency_checks: list[dict[str, object]]


@dataclass(frozen=True)
class StaleSidecarRepairFileEffects:
    stale_sidecar_repair_checks: list[dict[str, object]]


@dataclass(frozen=True)
class UninstallFileEffects:
    uninstall_checks: list[dict[str, object]]
    unexpected_uninstall_checks: list[dict[str, object]]


@dataclass(frozen=True)
class ScenarioFileEffectsAdapter:
    oracle: ScenarioFileEffectsOracle
    write_file_manifest: Callable[..., None]
    run_equivalence_check: Callable[[Scenario, dict[str, str], Path], list[dict[str, object]]]

    def seed_scenario_inputs(self, scenario: Scenario) -> None:
        self.oracle.seed_user_owned_content(scenario)

    def write_manifest(self, path: Path, roots: dict[str, Path], **kwargs: object) -> None:
        self.write_file_manifest(path, roots, **kwargs)

    def capture_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        return self.oracle.scenario_file_state(scenario)

    def installed_skill_sidecar_checks(self, scenario: Scenario, entry: InstallSurface) -> list[dict[str, object]]:
        return file_effect_sidecars.assert_installed_skill_sidecar(
            scenario,
            entry,
            self.oracle.roots,
            self.oracle.packaged_reference_resolution,
            self.oracle.expected_graphify_version,
        )

    def install_checks(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_expected_files(
            scenario,
            self.oracle.roots,
            self.installed_skill_sidecar_checks,
        ) + file_effect_surfaces.assert_scope_boundaries(scenario, self.oracle.roots)

    def unexpected_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.unexpected_checks_with_expected_keys(scenario, phase=phase)

    def unexpected_checks_with_expected_keys(
        self,
        scenario: Scenario,
        *,
        phase: str,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        return file_effect_generated_artifacts.assert_no_unexpected_graphify_files(
            scenario,
            self.oracle.roots,
            self.oracle.packaged_reference_resolution,
            phase=phase,
            expected_keys=expected_keys,
            pruned_file_walk_for=self.oracle.pruned_file_walk,
            generated_file_decision_for=self.oracle.generated_file_decision,
        )

    def archive_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        self.oracle.copy_generated_files(scenario, artifact_dir)

    def initial_install_effects(self, scenario: Scenario, artifact_dir: Path, *, phase: str) -> InitialInstallFileEffects:
        state_after_install = self.capture_state(scenario)
        install_checks = self.install_checks(scenario)
        unexpected_install_checks = self.unexpected_checks(scenario, phase=phase)
        return InitialInstallFileEffects(
            state_after_install=state_after_install,
            install_checks=install_checks,
            scope_checks=[],
            unexpected_install_checks=unexpected_install_checks,
        )

    def archive_initial_install_artifacts(self, scenario: Scenario, artifact_dir: Path) -> None:
        self.archive_generated_files(scenario, artifact_dir)

    def repeat_install_checks(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> list[dict[str, object]]:
        return file_effect_state.assert_idempotent_state(before, after) + self.unexpected_checks(scenario, phase=phase)

    def repeat_install_effects(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> RepeatInstallFileEffects:
        state_after_repeat = self.capture_state(scenario)
        return RepeatInstallFileEffects(
            state_after_repeat=state_after_repeat,
            idempotency_checks=self.repeat_install_checks(
                scenario,
                before,
                state_after_repeat,
                phase=phase,
            ),
        )

    def seed_stale_sidecar_repair(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.oracle.seed_stale_skill_sidecars(scenario)

    def stale_sidecar_repair_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.installed_skill_sidecars(scenario) + self.unexpected_checks(scenario, phase=phase)

    def installed_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_sidecars.assert_installed_skill_sidecars(
            scenario,
            self.oracle.roots,
            self.oracle.packaged_reference_resolution,
            self.oracle.expected_graphify_version,
        )

    def stale_sidecar_repair_effects(self, scenario: Scenario, *, phase: str) -> StaleSidecarRepairFileEffects:
        return StaleSidecarRepairFileEffects(
            stale_sidecar_repair_checks=self.stale_sidecar_repair_checks(scenario, phase=phase),
        )

    def uninstall_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.uninstalled_checks(scenario) + self.unexpected_checks(scenario, phase=phase)

    def uninstalled_skill_sidecar_checks(self, entry: InstallSurface) -> list[dict[str, object]]:
        return file_effect_sidecars.uninstalled_skill_sidecar_checks(entry, self.oracle.roots)

    def uninstalled_checks(self, scenario: Scenario) -> list[dict[str, object]]:
        return file_effect_surfaces.assert_uninstalled(
            scenario,
            self.oracle.roots,
            self.uninstalled_skill_sidecar_checks,
        )

    def uninstall_effects(self, scenario: Scenario, *, phase: str) -> UninstallFileEffects:
        return UninstallFileEffects(
            uninstall_checks=self.uninstall_checks(scenario, phase=phase),
            unexpected_uninstall_checks=[],
        )

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
                file_effect_state.expected_generated_relative_keys(
                    scenario.expected,
                    self.oracle.packaged_reference_resolution(scenario.target_name),
                )
            )
        uninstall_checks: list[dict[str, object]] = []
        for scenario in scenarios:
            uninstall_checks.extend(self.uninstalled_checks(scenario))
        unexpected_checks = self.unexpected_checks_with_expected_keys(
            runner_scenario,
            phase="universal_uninstall",
            expected_keys=expected_keys,
        )
        return _universal_uninstall_adapter_checks(
            install_checks,
            uninstall_checks,
            unexpected_checks,
        )

    def universal_install_effects(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.install_checks(scenario)

    def disposable_artifact_checks(self, disposable_path: Path, removed: bool) -> list[dict[str, object]]:
        return [check_record(disposable_path, removed, "removed" if removed else "still_exists")]

    def purge_checks(self, graphify_out: Path, purged: bool) -> list[dict[str, object]]:
        checks = self.disposable_artifact_checks(graphify_out, purged)
        for check in checks:
            if check["detail"] == "removed":
                check["detail"] = "purged"
        return checks
