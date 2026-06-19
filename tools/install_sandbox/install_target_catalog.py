from __future__ import annotations

from dataclasses import dataclass

try:
    from .install_target_models import (
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        InstallCommandVariant,
        InstallSurface,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        UniversalUninstallScenarioSpec,
    )
    from .install_target_scenarios import (
        _declared_install_variants,
        _dedupe_notes,
        _direct_project_install,
        _generic_install_command,
        _generic_uninstall_command,
        _scenario,
        _skill,
    )
    from . import install_target_selection as _selection
except ImportError:  # pragma: no cover - direct script import fallback
    from install_target_models import (  # type: ignore[no-redef]
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        InstallCommandVariant,
        InstallSurface,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        UniversalUninstallScenarioSpec,
    )
    from install_target_scenarios import (  # type: ignore[no-redef]
        _declared_install_variants,
        _dedupe_notes,
        _direct_project_install,
        _generic_install_command,
        _generic_uninstall_command,
        _scenario,
        _skill,
    )
    import install_target_selection as _selection  # type: ignore[no-redef]


@dataclass(frozen=True)
class ScenarioRegistry:
    specs: dict[str, PlatformSpec]
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...] = ()
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...] = ()

    @property
    def target_names(self) -> list[str]:
        return list(self.specs)

    @property
    def platform_names(self) -> list[str]:
        return self.target_names

    def target_spec(self, target_name: str) -> PlatformSpec:
        return _selection.target_spec(self.specs, target_name)

    def platform_spec(self, platform_name: str) -> PlatformSpec:
        return self.target_spec(platform_name)

    def selected_scopes(self, scope: str) -> list[str]:
        return _selection.selected_scopes(scope)

    def selected_targets(self, *, all_platforms: bool, target_name: str | None) -> list[str]:
        return _selection.selected_targets(self.specs, all_platforms=all_platforms, target_name=target_name)

    def selected_platforms(self, *, all_platforms: bool, platform_name: str | None) -> list[str]:
        return self.selected_targets(all_platforms=all_platforms, target_name=platform_name)

    def user_skill(self, platform_name: str) -> InstallSurface:
        return _selection.user_skill(self.specs, platform_name)

    def project_skill(self, platform_name: str) -> InstallSurface:
        return _selection.project_skill(self.specs, platform_name)

    def unsupported_scope_reason(self, platform_name: str, scope: str) -> str | None:
        return _selection.unsupported_scope_reason(self.specs, platform_name, scope)

    def direct_uninstall_command(self, platform_name: str) -> tuple[str, ...] | None:
        return _selection.direct_uninstall_command(self.specs, platform_name)

    def generic_install_command(self, platform_name: str, scope: str) -> tuple[str, ...]:
        return _selection.generic_install_command(platform_name, scope)

    def direct_install_command(self, platform_name: str, scope: str) -> tuple[str, ...] | None:
        return _selection.direct_install_command(self.specs, platform_name, scope)

    def install_variants_for_scope(self, platform_name: str, scope: str) -> tuple[InstallCommandVariant, ...]:
        return _selection.install_variants_for_scope(self.specs, platform_name, scope)

    def install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, ...]:
        return _selection.install_variants(self.specs, scenario)

    def make_scenario(self, platform_name: str, scope: str) -> Scenario | None:
        return _selection.make_scenario(self.specs, platform_name, scope)

    def target_scenarios(self, target_name: str, scope: str) -> list[Scenario]:
        return _selection.target_scenarios(self.specs, target_name, scope)

    def platform_scenarios(self, platform_name: str, scope: str) -> list[Scenario]:
        self.platform_spec(platform_name)
        return self.target_scenarios(platform_name, scope)

    def equivalent_install_command(self, scenario: Scenario) -> tuple[str, ...] | None:
        return _selection.equivalent_install_command(self.specs, scenario)

    def equivalent_install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
        return _selection.equivalent_install_variants(self.specs, scenario)

    def equivalence_status(self, scenario: Scenario) -> dict[str, object]:
        return _selection.equivalence_status(self.specs, scenario)

    def scenario_id(self, platform_name: str, scope: str) -> str:
        return _selection.scenario_id(platform_name, scope)

    def universal_uninstall_scenario_id(self, scope: str) -> str:
        spec = self.universal_uninstall_spec_for_scope(scope)
        return spec.scenario_id if spec is not None else f"universal-uninstall-{scope}"

    def purge_disposable_graphify_out_scenario_id(self) -> str:
        for spec in self.disposable_artifact_specs:
            if spec.disposable_path_relative == "graphify-out":
                return spec.scenario_id
        return "purge-disposable-graphify-out"

    def coverage_records(self, platforms: list[str], scope: str) -> list[dict[str, object]]:
        return _selection.coverage_records(self.specs, platforms, scope)

    def universal_uninstall_spec_for_scope(self, scope: str) -> UniversalUninstallScenarioSpec | None:
        return next((spec for spec in self.universal_uninstall_specs if spec.scope == scope), None)

    def universal_uninstall_scenarios(self, platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
        requested = set(platforms)
        selected_scopes = set(self.selected_scopes(scope))
        selected: list[SelectedUniversalUninstallScenario] = []
        for universal_spec in self.universal_uninstall_specs:
            if universal_spec.scope not in selected_scopes:
                continue
            scenarios = [
                self.make_scenario(platform_name, universal_spec.eligible_platform_scope)
                for platform_name, spec in self.specs.items()
                if platform_name in requested and universal_spec.eligible_platform_scope in spec.universal_uninstall_scopes
            ]
            runnable = tuple(scenario for scenario in scenarios if scenario is not None)
            if len(runnable) >= universal_spec.minimum_installed_scenarios:
                selected.append(SelectedUniversalUninstallScenario(universal_spec, runnable))
        return selected

    def universal_uninstall_groups(self, platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
        return [(selected.spec.scope, list(selected.installed_scenarios)) for selected in self.universal_uninstall_scenarios(platforms, scope)]

    def disposable_artifact_scenarios(self, scope: str) -> list[DisposableArtifactScenarioSpec]:
        return [spec for spec in self.disposable_artifact_specs if scope in spec.scope_eligibility]

    def target_runtime_validation_sections(self) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for platform in self.specs.values():
            for validation in platform.target_runtime_validation:
                key = (validation.section_title, validation.status)
                if key in seen:
                    continue
                seen.add(key)
                sections.append(validation.to_manifest())
        return sections

    def validate_roots(self, declared_roots: set[str]) -> None:
        unknown: set[str] = set()
        for platform in self.specs.values():
            for scope in platform.scopes.values():
                if scope.cwd_root not in declared_roots:
                    unknown.add(scope.cwd_root)
                unknown.update(entry.root for entry in scope.expected if entry.root not in declared_roots)
        unknown.update(spec.cwd_root for spec in self.universal_uninstall_specs if spec.cwd_root not in declared_roots)
        for spec in self.disposable_artifact_specs:
            if spec.cwd_root not in declared_roots:
                unknown.add(spec.cwd_root)
            if spec.disposable_path_root not in declared_roots:
                unknown.add(spec.disposable_path_root)
        if unknown:
            raise RuntimeError(f"unknown sandbox root declaration(s): {', '.join(sorted(unknown))}")

    def risk_notes(self, *notes: str, platform_name: str | None = None) -> tuple[str, ...]:
        ordered = list(notes)
        spec = self.specs.get(platform_name or "")
        if spec is not None and spec.simulated_linux_layout:
            ordered.append(SIMULATED_LINUX_LAYOUT_NOTE)
        return _dedupe_notes(*ordered)


InstallTargetCatalog = ScenarioRegistry
