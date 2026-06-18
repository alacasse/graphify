from __future__ import annotations

import ast
from pathlib import Path

from tools.install_sandbox import expected_effects
from tools.install_sandbox import file_effect_sidecars
from tools.install_sandbox import file_effect_state
from tools.install_sandbox import file_effects
from tools.install_sandbox import install_surface_core
from tools.install_sandbox import scenario_file_effects_adapter

# File-effects boundary guards live here. Oracle leaf behavior is split across
# topic modules, and ScenarioFileEffectsAdapter coverage lives in
# test_file_effects_adapter.py.


def test_file_effects_preserves_moved_compatibility_imports() -> None:
    assert file_effects.is_skill_effect is expected_effects.is_skill_effect
    assert file_effects.core_expected_manifest_relatives is file_effect_state.expected_manifest_relatives
    assert file_effects.ScenarioFileEffectsAdapter is scenario_file_effects_adapter.ScenarioFileEffectsAdapter
    assert file_effects.check_record is scenario_file_effects_adapter.check_record


def test_install_surface_core_facade_owns_only_path_resolution_glue() -> None:
    tree = ast.parse(Path(install_surface_core.__file__).read_text(encoding="utf-8"))
    function_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert function_names == {
        "resolve_install_root",
        "resolve_install_surface_path",
    }
    assert class_names == set()
    assert set(install_surface_core.__all__) >= function_names


def test_file_effect_oracle_boundary_rejects_pure_core_pass_throughs() -> None:
    adapter_methods = {
        "root_path",
        "expected_path",
        "skill_assertion_record",
        "installed_skill_reference_relatives",
        "tracked_skill_sidecar_relatives",
        "installed_reference_names",
        "check_skill_version",
        "check_references_tmp_absent",
        "check_packaged_references",
        "check_skill_reference_pointers",
        "assert_installed_skill_sidecar",
        "assert_installed_skill_sidecars",
        "seed_stale_skill_sidecars",
        "expected_manifest_relatives",
        "seed_user_owned_content",
        "installed_surface_observation",
        "expected_entry_status",
        "assert_expected_files",
        "uninstalled_surface_observation",
        "uninstalled_entry_status",
        "uninstalled_skill_sidecar_checks",
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
        for name, value in vars(file_effects.FileEffectOracle).items()
        if callable(value) and not name.startswith("_")
    }

    assert oracle_methods.isdisjoint(pure_core_pass_through_methods), (
        "FileEffectOracle should not grow pure Installer Core pass-through methods; "
        "call install_surface_core helpers directly instead."
    )
    assert oracle_methods == adapter_methods


def test_file_effects_tests_import_core_only_as_adapter_collaborator_module() -> None:
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
        "install_surface_core collaborators here and put direct core behavior tests "
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
    tree = ast.parse(Path(file_effects.__file__).read_text(encoding="utf-8"))
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
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
    }
    imported_from_state = {
        alias.name
        for node in ast.walk(tree)
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
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
        if alias.name == "*"
    }
    module_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    }
    imported_core_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    core_module_aliases = {
        alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    } | {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    direct_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    module_qualified_calls = {
        dotted
        for node in ast.walk(tree)
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
