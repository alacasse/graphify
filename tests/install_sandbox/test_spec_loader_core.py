from __future__ import annotations

import subprocess
import sys

from tools.install_sandbox.registry import spec_loader as registry_spec_loader
from tools.install_sandbox import spec_loader as root_spec_loader
from tools.install_sandbox.registry.spec_loader import load_default_registry, load_registry_from_data
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.targets import install_target_catalog
from tools.install_sandbox.targets import install_target_models
from tools.install_sandbox.targets import install_target_scenarios

from tests.install_sandbox.install_target_test_support import valid_registry_data as _valid_data


def test_loader_returns_existing_registry_dataclasses_with_defaults() -> None:
    registry = load_registry_from_data(_valid_data())
    user = registry.make_scenario("mini", "user")
    project = registry.make_scenario("mini", "project")
    spec = registry.platform_spec("mini")

    assert isinstance(registry, install_target_catalog.ScenarioRegistry)
    assert isinstance(spec, install_target_models.PlatformSpec)
    assert spec.display_name is None
    assert spec.target_kind == "product"
    assert user is not None
    assert user.install_command == ("graphify", "install", "--platform", "mini")
    assert user.uninstall_command is None
    assert user.cwd_root == "user_cwd"
    assert user.allowed_roots == ("home",)
    assert isinstance(user.expected[0], install_surface_models.SkillEffect)
    assert user.expected[0].skill_sidecar_expectation == install_surface_models.SkillSidecarExpectation()
    assert project is not None
    assert registry.install_variants(project) == (
        install_target_models.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "mini")),
        install_target_models.InstallCommandVariant("direct", ("graphify", "mini", "install", "--project")),
    )
    agents = next(entry for entry in project.expected if entry.relative == "AGENTS.md")
    assert isinstance(agents, install_surface_models.TextSectionEffect)
    assert agents.text_expectation.preserve_user_content
    assert agents.text_expectation.require_user_content_on_uninstall
    assert registry.universal_uninstall_specs[0].scenario_id == "universal-uninstall-project"


def test_loader_preserves_explicit_target_metadata() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["display_name"] = "Mini Target"
    data["platforms"]["mini"]["target_kind"] = "generic_standard"

    spec = load_registry_from_data(data).platform_spec("mini")

    assert spec.display_name == "Mini Target"
    assert spec.target_kind == "generic_standard"


def test_loader_preserves_explicit_no_project_install_equivalence() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["project"]["equivalent_install_command"] = None

    registry = load_registry_from_data(data)
    project = registry.make_scenario("mini", "project")

    assert project is not None
    assert registry.equivalent_install_command(project) is None


def test_default_registry_loads_and_returns_scenario_registry() -> None:
    registry = load_default_registry()

    assert isinstance(registry, install_target_catalog.ScenarioRegistry)
    assert type(registry) is install_target_catalog.InstallTargetCatalog
    assert install_target_catalog.InstallTargetCatalog is install_target_catalog.ScenarioRegistry
    assert registry.specs
    assert registry.universal_uninstall_specs == ()
    assert registry.disposable_artifact_specs == ()


def test_root_spec_loader_reexports_supported_registry_entrypoints() -> None:
    assert root_spec_loader.SpecLoaderError is registry_spec_loader.SpecLoaderError
    assert root_spec_loader.load_default_registry is registry_spec_loader.load_default_registry
    assert root_spec_loader.load_registry_from_data is registry_spec_loader.load_registry_from_data
    assert root_spec_loader.load_registry_from_dir is registry_spec_loader.load_registry_from_dir
    assert root_spec_loader.load_registry_from_yaml is registry_spec_loader.load_registry_from_yaml


def test_registry_spec_loader_is_owner_import_surface() -> None:
    assert registry_spec_loader.ScenarioRegistry is install_target_catalog.ScenarioRegistry
    assert registry_spec_loader.InstallTargetCatalog is install_target_catalog.InstallTargetCatalog
    assert registry_spec_loader._scenario is install_target_scenarios._scenario


def test_spec_loader_can_be_imported_without_platform_specs_first() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from tools.install_sandbox.spec_loader import load_registry_from_yaml; "
                "print(load_registry_from_yaml.__name__); "
                "print('tools.install_sandbox.platform_specs' in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["load_registry_from_yaml", "False"]
