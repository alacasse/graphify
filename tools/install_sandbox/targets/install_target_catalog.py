from __future__ import annotations

from dataclasses import dataclass

try:
    from . import install_target_harness_policy as _harness_policy
    from .install_target_models import (
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
    from targets import install_target_harness_policy as _harness_policy  # type: ignore[no-redef]
    from targets.install_target_models import (  # type: ignore[no-redef]
        DisposableArtifactScenarioSpec,
        InstallCommandVariant,
        InstallSurface,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        UniversalUninstallScenarioSpec,
    )
    from targets.install_target_scenarios import (  # type: ignore[no-redef]
        _declared_install_variants,
        _dedupe_notes,
        _direct_project_install,
        _generic_install_command,
        _generic_uninstall_command,
        _scenario,
        _skill,
    )
    from targets import install_target_selection as _selection  # type: ignore[no-redef]


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
        return _harness_policy.universal_uninstall_scenario_id(self.universal_uninstall_specs, scope)

    def purge_disposable_graphify_out_scenario_id(self) -> str:
        return _harness_policy.purge_disposable_graphify_out_scenario_id(self.disposable_artifact_specs)

    def coverage_records(self, platforms: list[str], scope: str) -> list[dict[str, object]]:
        return _selection.coverage_records(self.specs, platforms, scope)

    def universal_uninstall_spec_for_scope(self, scope: str) -> UniversalUninstallScenarioSpec | None:
        return _harness_policy.universal_uninstall_spec_for_scope(self.universal_uninstall_specs, scope)

    def universal_uninstall_scenarios(self, platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
        return _harness_policy.universal_uninstall_scenarios(self.specs, self.universal_uninstall_specs, platforms, scope)

    def universal_uninstall_groups(self, platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
        return _harness_policy.universal_uninstall_groups(self.specs, self.universal_uninstall_specs, platforms, scope)

    def disposable_artifact_scenarios(self, scope: str) -> list[DisposableArtifactScenarioSpec]:
        return _harness_policy.disposable_artifact_scenarios(self.disposable_artifact_specs, scope)

    def target_runtime_validation_sections(self) -> list[dict[str, object]]:
        return _harness_policy.target_runtime_validation_sections(self.specs)

    def validate_roots(self, declared_roots: set[str]) -> None:
        _harness_policy.validate_roots(
            self.specs,
            self.universal_uninstall_specs,
            self.disposable_artifact_specs,
            declared_roots,
        )

    def risk_notes(self, *notes: str, platform_name: str | None = None) -> tuple[str, ...]:
        return _harness_policy.risk_notes(self.specs, *notes, platform_name=platform_name)


InstallTargetCatalog = ScenarioRegistry
