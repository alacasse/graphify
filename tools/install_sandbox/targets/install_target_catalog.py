from __future__ import annotations

from dataclasses import dataclass

from . import install_target_selection as _selection
from .install_target_models import (
    DisposableArtifactScenarioSpec,
    InstallCommandVariant,
    InstallSurface,
    InstallTargetSpec,
    Scenario,
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


@dataclass(frozen=True)
class ScenarioRegistry:
    specs: dict[str, InstallTargetSpec]
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...] = ()
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...] = ()

    @property
    def target_names(self) -> list[str]:
        return list(self.specs)

    def target_spec(self, target_name: str) -> InstallTargetSpec:
        return _selection.target_spec(self.specs, target_name)

    def selected_scopes(self, scope: str) -> list[str]:
        return _selection.selected_scopes(scope)

    def selected_targets(self, *, all_platforms: bool, target_name: str | None) -> list[str]:
        return _selection.selected_targets(self.specs, all_platforms=all_platforms, target_name=target_name)

    def user_skill(self, target_name: str) -> InstallSurface:
        return _selection.user_skill(self.specs, target_name)

    def project_skill(self, target_name: str) -> InstallSurface:
        return _selection.project_skill(self.specs, target_name)

    def unsupported_scope_reason(self, target_name: str, scope: str) -> str | None:
        return _selection.unsupported_scope_reason(self.specs, target_name, scope)

    def direct_uninstall_command(self, target_name: str) -> tuple[str, ...] | None:
        return _selection.direct_uninstall_command(self.specs, target_name)

    def generic_install_command(self, target_name: str, scope: str) -> tuple[str, ...]:
        return _selection.generic_install_command(target_name, scope)

    def direct_install_command(self, target_name: str, scope: str) -> tuple[str, ...] | None:
        return _selection.direct_install_command(self.specs, target_name, scope)

    def install_variants_for_scope(self, target_name: str, scope: str) -> tuple[InstallCommandVariant, ...]:
        return _selection.install_variants_for_scope(self.specs, target_name, scope)

    def install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, ...]:
        return _selection.install_variants(self.specs, scenario)

    def make_scenario(self, target_name: str, scope: str) -> Scenario | None:
        return _selection.make_scenario(self.specs, target_name, scope)

    def target_scenarios(self, target_name: str, scope: str) -> list[Scenario]:
        return _selection.target_scenarios(self.specs, target_name, scope)

    def equivalent_install_command(self, scenario: Scenario) -> tuple[str, ...] | None:
        return _selection.equivalent_install_command(self.specs, scenario)

    def equivalent_install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
        return _selection.equivalent_install_variants(self.specs, scenario)

    def equivalence_status(self, scenario: Scenario) -> dict[str, object]:
        return _selection.equivalence_status(self.specs, scenario)

    def scenario_id(self, target_name: str, scope: str) -> str:
        return _selection.scenario_id(target_name, scope)

    def coverage_records(self, target_names: list[str], scope: str) -> list[dict[str, object]]:
        return _selection.coverage_records(self.specs, target_names, scope)

    def validate_target_roots(self, declared_roots: set[str]) -> None:
        unknown: set[str] = set()
        for target in self.specs.values():
            for scope in target.scopes.values():
                if scope.cwd_root not in declared_roots:
                    unknown.add(scope.cwd_root)
                unknown.update(entry.root for entry in scope.expected if entry.root not in declared_roots)
        if unknown:
            raise RuntimeError(f"unknown sandbox root declaration(s): {', '.join(sorted(unknown))}")


InstallTargetCatalog = ScenarioRegistry
