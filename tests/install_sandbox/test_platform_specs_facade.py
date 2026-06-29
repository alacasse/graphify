from __future__ import annotations

from tools.install_sandbox import platform_specs
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.targets import install_target_catalog, install_target_models

from install_target_test_support import REGISTRY


def test_install_target_aliases_are_identity_aliases() -> None:
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


def test_platform_specs_facade_does_not_export_private_install_target_helpers() -> None:
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


def test_platform_specs_facade_exports_legacy_and_install_target_names() -> None:
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


def test_install_target_fact_dataclasses_keep_facade_identity() -> None:
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


def test_install_surface_models_keep_owner_identity_across_remaining_facades() -> None:
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
