"""Temporary compatibility coverage for the root platform_specs facade.

Ordinary owner behavior should move to target and surface owner-module tests
before this facade is deleted.
"""

from __future__ import annotations

from tools.install_sandbox import platform_specs
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.targets import install_target_catalog, install_target_defaults, install_target_models

from install_target_test_support import REGISTRY


def test_temporary_platform_specs_facade_install_target_aliases_are_identity_aliases() -> None:
    assert platform_specs.InstallTargetSpec is platform_specs.PlatformSpec
    assert platform_specs.InstallTargetCatalog is platform_specs.ScenarioRegistry
    assert install_target_catalog.InstallTargetCatalog is install_target_catalog.ScenarioRegistry
    assert platform_specs.ScenarioRegistry is install_target_catalog.ScenarioRegistry
    assert platform_specs.InstallTargetCatalog is install_target_catalog.InstallTargetCatalog


def test_install_target_catalog_keeps_legacy_import_surface() -> None:
    expected_names = {
        "ScenarioRegistry",
        "InstallTargetCatalog",
    }

    for name in expected_names:
        assert hasattr(install_target_catalog, name), name
    assert install_target_catalog.InstallTargetCatalog is install_target_catalog.ScenarioRegistry


def test_temporary_platform_specs_facade_does_not_export_private_install_target_helpers() -> None:
    private_helper_names = {
        "_dedupe_notes",
        "_generic_install_command",
        "_generic_uninstall_command",
        "_direct_project_install",
        "_declared_install_variants",
        "_skill",
        "_scenario",
    }

    for name in private_helper_names:
        assert not hasattr(platform_specs, name), name


def test_temporary_platform_specs_facade_exports_legacy_and_install_target_names() -> None:
    legacy_platform_names = {
        "PlatformSpec",
        "ScenarioRegistry",
        "platform_spec",
        "platform_scenarios",
        "ALL_PLATFORMS",
        "SANDBOX_PLATFORM_SPECS",
        "DEFAULT_SCENARIO_REGISTRY",
    }
    install_target_names = {
        "InstallTargetSpec",
        "InstallTargetCatalog",
        "default_install_target_catalog",
        "install_target_specs",
        "install_target_spec",
        "install_target_scenarios",
    }

    for name in legacy_platform_names | install_target_names:
        assert hasattr(platform_specs, name), name
    for name in ("platform_names", "target_names", "selected_platforms", "selected_targets", "platform_scenarios", "target_scenarios"):
        assert hasattr(REGISTRY, name), name
    assert platform_specs.DEFAULT_SCENARIO_REGISTRY is REGISTRY
    assert platform_specs.SANDBOX_PLATFORM_SPECS is REGISTRY.specs
    assert platform_specs.ALL_PLATFORMS == REGISTRY.platform_names
    assert platform_specs.platform_spec("codex") is REGISTRY.platform_spec("codex")
    assert platform_specs.platform_scenarios("cursor", "both") == REGISTRY.platform_scenarios("cursor", "both")


def test_temporary_platform_specs_facade_install_target_helpers_are_owner_aliases() -> None:
    helper_names = (
        "default_install_target_catalog",
        "install_target_specs",
        "install_target_spec",
        "install_target_scenarios",
        "platform_spec",
        "platform_scenarios",
        "make_scenario",
        "risk_notes",
        "validate_roots",
        "target_runtime_validation_sections",
    )

    for name in helper_names:
        assert getattr(platform_specs, name) is getattr(install_target_defaults, name)
    assert (
        platform_specs.target_runtime_validation_sections()
        == install_target_defaults.target_runtime_validation_sections()
    )


def test_temporary_platform_specs_facade_lazy_defaults_share_owner_cache(monkeypatch) -> None:
    registry = install_target_catalog.ScenarioRegistry(
        {
            "cached-target": install_target_models.PlatformSpec(
                name="cached-target",
                scopes={
                    "project": install_target_models.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(install_target_models.InstallSurface("project", "cached.txt"),),
                    )
                },
            )
        }
    )

    monkeypatch.setattr(install_target_defaults, "_DEFAULT_SCENARIO_REGISTRY", registry)
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        monkeypatch.delitem(platform_specs.__dict__, name, raising=False)
        monkeypatch.delitem(install_target_defaults.__dict__, name, raising=False)

    assert platform_specs.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry
    assert platform_specs.__getattr__("SANDBOX_PLATFORM_SPECS") is registry.specs
    assert platform_specs.__getattr__("ALL_PLATFORMS") == ["cached-target"]
    assert install_target_defaults.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry

    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        platform_specs.__dict__.pop(name, None)
        install_target_defaults.__dict__.pop(name, None)


def test_temporary_platform_specs_facade_install_target_fact_dataclasses_keep_facade_identity() -> None:
    model_names = (
        "GeneratedFileExpectation",
        "InstallCommandVariant",
        "TargetRuntimeValidationSpec",
        "UniversalUninstallScenarioSpec",
        "SelectedUniversalUninstallScenario",
        "DisposableSeedFile",
        "DisposableArtifactScenarioSpec",
        "Scenario",
        "ScopeSpec",
        "ReferenceBundle",
        "PlatformSpec",
        "InstallTargetSpec",
    )

    for name in model_names:
        exported = getattr(platform_specs, name)
        assert getattr(install_target_models, name) is exported

    scope = platform_specs.ScopeSpec(
        install_command=("tool", "install"),
        uninstall_command=("tool", "uninstall"),
        cwd_root="project",
        expected=(platform_specs.InstallSurface("project", "graphify.txt"),),
    )
    spec = platform_specs.InstallTargetSpec(name="facade-target", scopes={"project": scope})
    registry = platform_specs.InstallTargetCatalog({"facade-target": spec})
    scenario = registry.make_scenario("facade-target", "project")

    assert type(scope) is platform_specs.ScopeSpec
    assert type(spec) is platform_specs.PlatformSpec
    assert platform_specs.InstallTargetSpec is platform_specs.PlatformSpec
    assert platform_specs.InstallTargetCatalog is platform_specs.ScenarioRegistry
    assert scenario is not None
    assert type(scenario) is platform_specs.Scenario
    assert scenario.expected[0].__class__ is platform_specs.InstallSurface


def test_temporary_platform_specs_facade_install_surface_models_keep_owner_identity() -> None:
    model_names = (
        "JsonHookExpectation",
        "JsonPluginExpectation",
        "JsonExpectation",
        "TextExpectation",
        "SkillSidecarExpectation",
        "FileEffect",
        "SkillEffect",
        "TextSectionEffect",
        "JsonHooksEffect",
        "JsonPluginEffect",
        "InstallSurface",
        "ExpectedPath",
        "effect_type_name",
        "is_skill_effect",
        "is_text_section_effect",
        "is_json_effect",
    )

    for name in model_names:
        owner = getattr(install_surface_models, name)
        assert getattr(platform_specs, name) is owner
        if name not in {"effect_type_name", "is_skill_effect", "is_text_section_effect", "is_json_effect"}:
            assert getattr(install_target_models, name) is owner
