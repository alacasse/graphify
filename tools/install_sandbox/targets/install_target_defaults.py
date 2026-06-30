from __future__ import annotations

from . import install_target_harness_policy as _harness_policy
from .install_target_catalog import ScenarioRegistry
from .install_target_models import (
    DisposableArtifactScenarioSpec,
    InstallCommandVariant,
    InstallSurface,
    PlatformSpec,
    Scenario,
    SelectedUniversalUninstallScenario,
)


_DEFAULT_SCENARIO_REGISTRY: ScenarioRegistry | None = None
_LAZY_DEFAULT_NAMES = {
    "DEFAULT_SCENARIO_REGISTRY",
    "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS",
    "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS",
}


def _import_load_default_registry():
    from ..registry.spec_loader import load_default_registry

    return load_default_registry


def _load_default_scenario_registry() -> ScenarioRegistry:
    global _DEFAULT_SCENARIO_REGISTRY
    if _DEFAULT_SCENARIO_REGISTRY is None:
        _DEFAULT_SCENARIO_REGISTRY = _import_load_default_registry()()
    return _DEFAULT_SCENARIO_REGISTRY


def _default_export(name: str):
    registry = _load_default_scenario_registry()
    if name == "DEFAULT_SCENARIO_REGISTRY":
        return registry
    if name == "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS":
        return registry.universal_uninstall_specs
    if name == "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS":
        return registry.disposable_artifact_specs
    raise AttributeError(name)


def __getattr__(name: str):
    if name in _LAZY_DEFAULT_NAMES:
        value = _default_export(name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def default_install_target_catalog() -> ScenarioRegistry:
    return _load_default_scenario_registry()


def install_target_specs() -> dict[str, PlatformSpec]:
    return _load_default_scenario_registry().specs


def install_target_spec(target_name: str) -> PlatformSpec:
    return _load_default_scenario_registry().target_spec(target_name)


def install_target_scenarios(target_name: str, scope: str) -> list[Scenario]:
    return _load_default_scenario_registry().target_scenarios(target_name, scope)


def user_skill(platform_name: str) -> InstallSurface:
    return _load_default_scenario_registry().user_skill(platform_name)


def project_skill(platform_name: str) -> InstallSurface:
    return _load_default_scenario_registry().project_skill(platform_name)


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return _load_default_scenario_registry().unsupported_scope_reason(platform_name, scope)


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().direct_uninstall_command(platform_name)


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return _load_default_scenario_registry().generic_install_command(platform_name, scope)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().direct_install_command(platform_name, scope)


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().equivalent_install_command(scenario)


def equivalent_install_variants(
    scenario: Scenario,
) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    return _load_default_scenario_registry().equivalent_install_variants(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return _load_default_scenario_registry().equivalence_status(scenario)


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    return _load_default_scenario_registry().make_scenario(platform_name, scope)


def target_runtime_validation_sections() -> list[dict[str, object]]:
    registry = _load_default_scenario_registry()
    return _harness_policy.target_runtime_validation_sections(registry.specs)


def universal_uninstall_scenarios(
    platforms: list[str], scope: str
) -> list[SelectedUniversalUninstallScenario]:
    registry = _load_default_scenario_registry()
    return _harness_policy.universal_uninstall_scenarios(
        registry.specs,
        registry.universal_uninstall_specs,
        platforms,
        scope,
    )


def disposable_artifact_scenarios(scope: str) -> list[DisposableArtifactScenarioSpec]:
    registry = _load_default_scenario_registry()
    return _harness_policy.disposable_artifact_scenarios(registry.disposable_artifact_specs, scope)


def validate_roots(declared_roots: set[str]) -> None:
    registry = _load_default_scenario_registry()
    _harness_policy.validate_roots(
        registry.specs,
        registry.universal_uninstall_specs,
        registry.disposable_artifact_specs,
        declared_roots,
    )


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    registry = _load_default_scenario_registry()
    return _harness_policy.risk_notes(registry.specs, *notes, platform_name=platform_name)
