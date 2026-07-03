from __future__ import annotations

from . import install_target_harness_policy as _harness_policy
from .install_target_catalog import InstallTargetCatalog
from .install_target_models import (
    DisposableArtifactScenarioSpec,
    InstallCommandVariant,
    InstallSurface,
    InstallTargetSpec,
    Scenario,
    SelectedUniversalUninstallScenario,
)


_DEFAULT_INSTALL_TARGET_CATALOG: InstallTargetCatalog | None = None
_LAZY_DEFAULT_NAMES = {
    "DEFAULT_INSTALL_TARGET_CATALOG",
    "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS",
    "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS",
}


def _import_load_default_registry():
    from ..registry.spec_loader import load_default_registry

    return load_default_registry


def _load_default_install_target_catalog() -> InstallTargetCatalog:
    global _DEFAULT_INSTALL_TARGET_CATALOG
    if _DEFAULT_INSTALL_TARGET_CATALOG is None:
        _DEFAULT_INSTALL_TARGET_CATALOG = _import_load_default_registry()()
    return _DEFAULT_INSTALL_TARGET_CATALOG


def _default_export(name: str):
    catalog = _load_default_install_target_catalog()
    if name == "DEFAULT_INSTALL_TARGET_CATALOG":
        return catalog
    if name == "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS":
        return catalog.universal_uninstall_specs
    if name == "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS":
        return catalog.disposable_artifact_specs
    raise AttributeError(name)


def __getattr__(name: str):
    if name in _LAZY_DEFAULT_NAMES:
        value = _default_export(name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def default_install_target_catalog() -> InstallTargetCatalog:
    return _load_default_install_target_catalog()


def install_target_specs() -> dict[str, InstallTargetSpec]:
    return _load_default_install_target_catalog().specs


def install_target_spec(target_name: str) -> InstallTargetSpec:
    return _load_default_install_target_catalog().target_spec(target_name)


def install_target_scenarios(target_name: str, scope: str) -> list[Scenario]:
    return _load_default_install_target_catalog().target_scenarios(target_name, scope)


def user_skill(target_name: str) -> InstallSurface:
    return _load_default_install_target_catalog().user_skill(target_name)


def project_skill(target_name: str) -> InstallSurface:
    return _load_default_install_target_catalog().project_skill(target_name)


def unsupported_scope_reason(target_name: str, scope: str) -> str | None:
    return _load_default_install_target_catalog().unsupported_scope_reason(target_name, scope)


def direct_uninstall_command(target_name: str) -> tuple[str, ...] | None:
    return _load_default_install_target_catalog().direct_uninstall_command(target_name)


def generic_install_command(target_name: str, scope: str) -> tuple[str, ...]:
    return _load_default_install_target_catalog().generic_install_command(target_name, scope)


def direct_install_command(target_name: str, scope: str) -> tuple[str, ...] | None:
    return _load_default_install_target_catalog().direct_install_command(target_name, scope)


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    return _load_default_install_target_catalog().equivalent_install_command(scenario)


def equivalent_install_variants(
    scenario: Scenario,
) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    return _load_default_install_target_catalog().equivalent_install_variants(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return _load_default_install_target_catalog().equivalence_status(scenario)


def make_scenario(target_name: str, scope: str) -> Scenario | None:
    return _load_default_install_target_catalog().make_scenario(target_name, scope)


def target_runtime_validation_sections() -> list[dict[str, object]]:
    catalog = _load_default_install_target_catalog()
    return _harness_policy.target_runtime_validation_sections(catalog.specs)


def universal_uninstall_scenarios(
    target_names: list[str], scope: str
) -> list[SelectedUniversalUninstallScenario]:
    catalog = _load_default_install_target_catalog()
    return _harness_policy.universal_uninstall_scenarios(
        catalog.specs,
        catalog.universal_uninstall_specs,
        target_names,
        scope,
    )


def disposable_artifact_scenarios(scope: str) -> list[DisposableArtifactScenarioSpec]:
    catalog = _load_default_install_target_catalog()
    return _harness_policy.disposable_artifact_scenarios(catalog.disposable_artifact_specs, scope)


def validate_roots(declared_roots: set[str]) -> None:
    catalog = _load_default_install_target_catalog()
    _harness_policy.validate_roots(
        catalog.specs,
        catalog.universal_uninstall_specs,
        catalog.disposable_artifact_specs,
        declared_roots,
    )


def risk_notes(*notes: str, target_name: str | None = None) -> tuple[str, ...]:
    catalog = _load_default_install_target_catalog()
    return _harness_policy.risk_notes(catalog.specs, *notes, target_name=target_name)
