from __future__ import annotations

import ast
from pathlib import Path

from tools.install_sandbox.effects import file_effect_oracle
from tools.install_sandbox.effects import file_effect_sidecars
from tools.install_sandbox.effects import file_effect_surfaces
from tools.install_sandbox.effects import file_effect_state
from tools.install_sandbox.effects import scenario_file_effects_adapter
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.surfaces import path_resolution

# File-effects package and oracle boundary guards live here. Behavior assertions
# stay with topic-owner tests such as test_file_effects_sidecars.py,
# test_file_effects_generated.py, test_file_effects_observations.py, and
# test_file_effects_adapter.py.


def test_file_effects_package_tests_do_not_claim_topic_behavior_ownership() -> None:
    topic_owner_tests = {
        "sidecar": "test_file_effects_sidecars.py",
        "surface": "test_file_effects_observations.py",
        "generated": "test_file_effects_generated.py",
        "lifecycle_adapter": "test_file_effects_adapter.py",
    }

    for filename in topic_owner_tests.values():
        assert (Path(__file__).parent / filename).exists()

    assert scenario_file_effects_adapter.ScenarioFileEffectsAdapter.__name__ == "ScenarioFileEffectsAdapter"
    assert file_effect_oracle.FileEffectOracle.__name__ == "FileEffectOracle"


def test_path_resolution_owner_resolves_roots_and_surface_paths() -> None:
    roots = {
        "project": Path("/sandbox/project"),
        "home": Path("/sandbox/home"),
    }

    assert path_resolution.resolve_install_root("home", roots) == Path("/sandbox/home")
    assert path_resolution.resolve_install_surface_path(
        install_surface_models.InstallSurface("project", "AGENTS.md"),
        roots,
    ) == Path("/sandbox/project/AGENTS.md")


def test_path_resolution_owner_rejects_unknown_roots() -> None:
    roots = {"project": Path("/sandbox/project")}

    try:
        path_resolution.resolve_install_root("missing", roots)
    except AssertionError as exc:
        assert str(exc) == "unknown root: missing"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unknown root did not raise")


def test_file_effect_owners_import_path_resolution_helpers_from_owner_module() -> None:
    owner_modules = {
        file_effect_oracle: {"resolve_install_root"},
        file_effect_surfaces: {"resolve_install_surface_path"},
    }

    for module, expected_owner_helpers in owner_modules.items():
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported_owner_helpers = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("surfaces.path_resolution")
            for alias in node.names
        }
        imported_core_helpers = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("install_surface_core")
            for alias in node.names
        }

        assert expected_owner_helpers <= imported_owner_helpers
        assert imported_core_helpers.isdisjoint(
            {"resolve_install_root", "resolve_install_surface_path"}
        )


def test_file_effect_oracle_boundary_rejects_pure_core_pass_throughs() -> None:
    oracle_adapter_methods = {
        "root_path",
        "seed_stale_skill_sidecars",
        "expected_manifest_relatives",
        "seed_user_owned_content",
        "assert_expected_files",
        "assert_uninstalled",
        "pruned_file_walk",
        "assert_no_unexpected_graphify_files",
        "assert_scope_boundaries",
        "file_fingerprint",
        "scenario_file_state",
        "generated_file_size",
        "file_mentions_expected_generated_marker",
        "generated_file_decision",
        "is_relevant_generated_file",
        "copy_generated_files",
    }
    pure_core_pass_through_methods = {
        "is_skill_expected",
        "skill_sidecar_expectation",
        "skill_dir_for_entry",
        "skill_relative_dir",
        "skill_version_relative",
        "skill_references_relative",
        "skill_references_tmp_relative",
        "expected_skill_sidecar_relatives",
        "reference_sidecar_expectation",
        "skill_reference_pointers",
        "progressive_skill_entries",
        "graphify_section_removed",
        "expected_generated_relative_keys",
        "expected_generated_relative_keys_for_scenarios",
        "is_small_text_candidate",
        "is_expected_generated_key",
        "is_skill_sidecar_relative",
        "seeded_text",
        "should_exclude_generated_path",
        "should_seed_stale_graphify_section",
        "should_seed_user_content",
    }

    oracle_methods = {
        name
        for name, value in vars(file_effect_oracle.FileEffectOracle).items()
        if callable(value) and not name.startswith("_")
    }

    assert oracle_methods.isdisjoint(pure_core_pass_through_methods), (
        "FileEffectOracle should not grow pure Installer Core pass-through methods; "
        "call surface owner helpers directly instead."
    )
    assert oracle_methods == oracle_adapter_methods


def test_file_effects_tests_do_not_import_install_surface_core_helpers() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    core_test_modules = tuple(Path(__file__).parent.glob("test_install_surface_core*.py"))

    imported_core_helpers = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
    }

    assert core_test_modules, "direct Installer Core behavior tests belong in test_install_surface_core*.py"
    assert imported_core_helpers == set(), (
        "Keep test_file_effects.py adapter-owned; use module-qualified "
        "surface-owner collaborators here and put direct surface behavior tests "
        "in test_install_surface_core*.py."
    )


def test_file_effects_does_not_import_or_call_path_reading_core_wrappers() -> None:
    legacy_wrappers = {
        "expected_kind_status",
        "install_surface_kind_status",
        "json_marker_status",
        "text_marker_status",
        "installed_surface_status",
        "uninstalled_surface_status",
        "file_fingerprint",
    }
    topic_owned_helpers = {
        "expected_generated_relative_keys",
        "expected_manifest_relatives",
        "idempotency_state_changes",
        "planned_state_entries",
        "user_content_seed_plans",
    }
    oracle_tree = ast.parse(Path(file_effect_oracle.__file__).read_text(encoding="utf-8"))
    sidecar_tree = ast.parse(Path(file_effect_sidecars.__file__).read_text(encoding="utf-8"))
    state_tree = ast.parse(Path(file_effect_state.__file__).read_text(encoding="utf-8"))

    def dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            if parent is None:
                return None
            return f"{parent}.{node.attr}"
        return None

    imported_from_core = {
        alias.name
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
    }
    imported_from_state = {
        alias.name
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_state")
        for alias in node.names
    }
    state_module_imported_from_state = {
        alias.name
        for node in ast.walk(state_tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_state")
        for alias in node.names
    }
    sidecar_imported_from_state = {
        alias.name
        for node in ast.walk(sidecar_tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_state")
        for alias in node.names
    }
    wildcard_core_imports = {
        node.module
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
        if alias.name == "*"
    }
    module_imports = {
        alias.name
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    }
    imported_core_modules = {
        alias.name
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    core_module_aliases = {
        alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    } | {
        alias.asname or alias.name
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    direct_calls = {
        node.func.id
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    module_qualified_calls = {
        dotted
        for node in ast.walk(oracle_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in legacy_wrappers
        if (dotted := dotted_name(node.func)) is not None
        and (
            dotted.rsplit(".", maxsplit=1)[0] in core_module_aliases
            or ".install_surface_core." in dotted
        )
    }

    assert not wildcard_core_imports
    assert imported_from_core.isdisjoint(legacy_wrappers)
    assert imported_from_core.isdisjoint(topic_owned_helpers)
    assert imported_from_state.isdisjoint(topic_owned_helpers)
    assert topic_owned_helpers <= state_module_imported_from_state
    assert "stale_sidecar_seed_plans" in sidecar_imported_from_state
    assert not module_imports
    assert not imported_core_modules
    assert direct_calls.isdisjoint(legacy_wrappers)
    assert not module_qualified_calls
