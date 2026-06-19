from __future__ import annotations

try:
    from .install_target_models import (
        GRAPHIFY_MARKER,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        ExpectedPath,
        FileEffect,
        GeneratedFileExpectation,
        InstallCommandVariant,
        InstallTargetSpec,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        PlatformSpec,
        ReferenceBundle,
        Scenario,
        ScopeSpec,
        SelectedUniversalUninstallScenario,
        SkillEffect,
        SkillSidecarExpectation,
        TargetRuntimeValidationSpec,
        TextExpectation,
        TextSectionEffect,
        UniversalUninstallScenarioSpec,
    )
    from .install_target_catalog import (
        InstallTargetCatalog,
        ScenarioRegistry,
        _declared_install_variants,
        _dedupe_notes,
        _direct_project_install,
        _generic_install_command,
        _generic_uninstall_command,
        _scenario,
        _skill,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from install_target_models import (  # type: ignore[no-redef]
        GRAPHIFY_MARKER,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        ExpectedPath,
        FileEffect,
        GeneratedFileExpectation,
        InstallCommandVariant,
        InstallTargetSpec,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        PlatformSpec,
        ReferenceBundle,
        Scenario,
        ScopeSpec,
        SelectedUniversalUninstallScenario,
        SkillEffect,
        SkillSidecarExpectation,
        TargetRuntimeValidationSpec,
        TextExpectation,
        TextSectionEffect,
        UniversalUninstallScenarioSpec,
    )
    from install_target_catalog import (  # type: ignore[no-redef]
        InstallTargetCatalog,
        ScenarioRegistry,
        _declared_install_variants,
        _dedupe_notes,
        _direct_project_install,
        _generic_install_command,
        _generic_uninstall_command,
        _scenario,
        _skill,
    )


_DEFAULT_SCENARIO_REGISTRY: ScenarioRegistry | None = None
_LAZY_DEFAULT_NAMES = {
    "DEFAULT_SCENARIO_REGISTRY",
    "SANDBOX_PLATFORM_SPECS",
    "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS",
    "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS",
    "ALL_PLATFORMS",
}


def _import_load_default_registry():
    try:
        from .spec_loader import load_default_registry
    except ImportError:  # pragma: no cover - direct script import fallback
        from spec_loader import load_default_registry  # type: ignore[no-redef]
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
    if name == "SANDBOX_PLATFORM_SPECS":
        return registry.specs
    if name == "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS":
        return registry.universal_uninstall_specs
    if name == "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS":
        return registry.disposable_artifact_specs
    if name == "ALL_PLATFORMS":
        return list(registry.specs)
    raise AttributeError(name)


def __getattr__(name: str):
    if name in _LAZY_DEFAULT_NAMES:
        value = _default_export(name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def sandbox_platform_specs() -> dict[str, PlatformSpec]:
    return install_target_specs()


def default_install_target_catalog() -> ScenarioRegistry:
    return _load_default_scenario_registry()


def install_target_specs() -> dict[str, PlatformSpec]:
    return _load_default_scenario_registry().specs


def install_target_spec(target_name: str) -> PlatformSpec:
    return _load_default_scenario_registry().target_spec(target_name)


def install_target_scenarios(target_name: str, scope: str) -> list[Scenario]:
    return _load_default_scenario_registry().target_scenarios(target_name, scope)


def platform_spec(platform_name: str) -> PlatformSpec:
    return _load_default_scenario_registry().platform_spec(platform_name)


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


def equivalent_install_variants(scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    return _load_default_scenario_registry().equivalent_install_variants(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return _load_default_scenario_registry().equivalence_status(scenario)


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    return _load_default_scenario_registry().platform_scenarios(platform_name, scope)


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    return _load_default_scenario_registry().make_scenario(platform_name, scope)


def target_runtime_validation_sections() -> list[dict[str, object]]:
    return _load_default_scenario_registry().target_runtime_validation_sections()


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
    return _load_default_scenario_registry().universal_uninstall_scenarios(platforms, scope)


def disposable_artifact_scenarios(scope: str) -> list[DisposableArtifactScenarioSpec]:
    return _load_default_scenario_registry().disposable_artifact_scenarios(scope)


def validate_roots(declared_roots: set[str]) -> None:
    _load_default_scenario_registry().validate_roots(declared_roots)


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    return _load_default_scenario_registry().risk_notes(*notes, platform_name=platform_name)
