from __future__ import annotations

import ast
from pathlib import Path

from tools.install_sandbox.harness_specs import (
    DEFAULT_SANDBOX_ROOT_REGISTRY,
    SandboxRootRegistry,
    SandboxRootSpec,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_NAMED_ROOT_APIS = {
    "env_entries",
    "env_roots",
    "install_surface_root_names",
    "policy_cwd_root_names",
    "preflight_roots",
    "reset_roots",
    "root_names",
    "runtime_paths",
    "sandbox_path_assertion_roots",
    "scenario_root_names",
    "scenario_root_paths",
    "volume_roots",
}
PRODUCTION_CALLED_ROLE_NAMED_ROOT_APIS = ROLE_NAMED_ROOT_APIS - {
    "scenario_root_names",
}
PRODUCTION_ROOT_REGISTRY_CALLERS = {
    "tools/install_sandbox/registry/spec_harness_policy_inputs.py",
    "tools/install_sandbox/registry/spec_install_surfaces.py",
    "tools/install_sandbox/registry/spec_loader.py",
    "tools/install_sandbox/registry/spec_target_facts.py",
    "tools/install_sandbox/runtime/container_runtime.py",
    "tools/install_sandbox/runtime/sandbox_run_environment.py",
    "tools/install_sandbox/validation_plan.py",
}


def _sandbox_python_files() -> list[Path]:
    return sorted(
        [
            *Path("tools/install_sandbox").glob("**/*.py"),
            *Path("tests/install_sandbox").glob("**/*.py"),
        ]
    )


def _production_sandbox_python_files() -> list[Path]:
    return sorted(
        path
        for path in Path("tools/install_sandbox").glob("**/*.py")
        if path.as_posix() != "tools/install_sandbox/harness_specs.py"
    )


class _AttributeCallVisitor(ast.NodeVisitor):
    def __init__(self, names: set[str], relpath: str) -> None:
        self.names = names
        self.relpath = relpath
        self.calls: set[tuple[str, str, str]] = set()
        self.definitions: set[tuple[str, str]] = set()
        self._scope: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name in self.names:
            self.definitions.add((node.name, self.relpath))
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in self.names:
            self.calls.add((node.func.attr, self.relpath, self._scope[-1] if self._scope else "<module>"))
        self.generic_visit(node)


def _attribute_calls_and_definitions(names: set[str]) -> tuple[set[tuple[str, str, str]], set[tuple[str, str]]]:
    calls: set[tuple[str, str, str]] = set()
    definitions: set[tuple[str, str]] = set()
    for relpath in _sandbox_python_files():
        tree = ast.parse((REPO_ROOT / relpath).read_text(encoding="utf-8"))
        visitor = _AttributeCallVisitor(names, relpath.as_posix())
        visitor.visit(tree)
        calls.update(visitor.calls)
        definitions.update(visitor.definitions)
    return calls, definitions


def _literal_string_set(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return None
    values: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.add(element.value)
    return values


def _production_literal_root_role_sets(registry: SandboxRootRegistry) -> dict[str, list[set[str]]]:
    root_role_sets = tuple(
        {
            frozenset(registry.root_names()),
            frozenset(registry.policy_cwd_root_names()),
        }
    )
    literal_sets: dict[str, list[set[str]]] = {}
    for relpath in _production_sandbox_python_files():
        tree = ast.parse((REPO_ROOT / relpath).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            literal_set = _literal_string_set(node)
            if literal_set is not None and frozenset(literal_set) in root_role_sets:
                literal_sets.setdefault(relpath.as_posix(), []).append(literal_set)
    return literal_sets


def test_default_sandbox_root_registry_characterizes_current_role_groups() -> None:
    registry = DEFAULT_SANDBOX_ROOT_REGISTRY

    assert isinstance(registry, SandboxRootRegistry)
    assert all(isinstance(root, SandboxRootSpec) for root in registry.roots)
    assert tuple(root.name for root in registry.roots) == (
        "home",
        "xdg_config_home",
        "project",
        "user_cwd",
        "repo_mount",
        "src",
        "output",
    )
    assert registry.root_names() == {
        "home",
        "xdg_config_home",
        "project",
        "user_cwd",
        "repo_mount",
        "src",
        "output",
    }
    assert registry.install_surface_root_names() == {"home", "project", "user_cwd"}
    assert registry.scenario_root_names() == ("home", "project", "user_cwd")
    assert registry.policy_cwd_root_names() == registry.root_names()
    scenario_root_paths = registry.scenario_root_paths(registry.runtime_paths({}))
    assert scenario_root_paths == {
        "home": Path("/tmp/graphify-home"),
        "project": Path("/tmp/graphify-project"),
        "user_cwd": Path("/tmp/graphify-user-cwd"),
    }
    assert tuple(scenario_root_paths) == ("home", "project", "user_cwd")
    assert tuple(root.name for root in registry.reset_roots()) == ("home", "project", "user_cwd")
    assert tuple(root.name for root in registry.preflight_roots()) == (
        "home",
        "xdg_config_home",
        "project",
        "repo_mount",
    )
    assert tuple(root.name for root in registry.volume_roots()) == ("repo_mount", "output")
    assert registry.env_entries() == {
        "HOME": "/tmp/graphify-home",
        "XDG_CONFIG_HOME": "/tmp/graphify-home/.config",
        "GRAPHIFY_PROJECT": "/tmp/graphify-project",
        "GRAPHIFY_REPO_MOUNT": "/mnt/graphify-repo",
        "GRAPHIFY_SRC": "/tmp/graphify-src",
        "GRAPHIFY_OUTPUT": "/sandbox-out",
    }
    assert tuple(root.name for root in registry.env_roots()) == (
        "home",
        "xdg_config_home",
        "project",
        "repo_mount",
        "src",
        "output",
    )
    assert {
        root.name: root.sandbox_path_required
        for root in registry.roots
        if root.sandbox_path_required is not None
    } == {
        "home": "/tmp/graphify-home",
        "xdg_config_home": "/tmp/graphify-home/.config",
        "project": "/tmp/graphify-project",
    }
    assert tuple(root.name for root in registry.sandbox_path_assertion_roots()) == (
        "home",
        "xdg_config_home",
        "project",
    )


def test_default_sandbox_root_registry_runtime_paths_use_env_overrides_only_for_env_roots() -> None:
    registry = DEFAULT_SANDBOX_ROOT_REGISTRY

    paths = registry.runtime_paths(
        {
            "HOME": "/custom/home",
            "XDG_CONFIG_HOME": "/custom/config",
            "GRAPHIFY_PROJECT": "/custom/project",
            "GRAPHIFY_REPO_MOUNT": "/custom/repo",
            "GRAPHIFY_SRC": "/custom/src",
            "GRAPHIFY_OUTPUT": "/custom/out",
        }
    )

    assert paths == {
        "home": Path("/custom/home"),
        "xdg_config_home": Path("/custom/config"),
        "project": Path("/custom/project"),
        "user_cwd": Path("/tmp/graphify-user-cwd"),
        "repo_mount": Path("/custom/repo"),
        "src": Path("/custom/src"),
        "output": Path("/custom/out"),
    }


def test_production_sandbox_root_callers_use_role_named_apis() -> None:
    calls, _definitions = _attribute_calls_and_definitions(ROLE_NAMED_ROOT_APIS)
    production_calls = {
        name
        for name, relpath, _scope in calls
        if relpath.startswith("tools/install_sandbox/")
        and relpath != "tools/install_sandbox/harness_specs.py"
    }

    assert PRODUCTION_CALLED_ROLE_NAMED_ROOT_APIS <= production_calls


def test_production_sandbox_root_callers_do_not_rebuild_registry_role_sets() -> None:
    assert _production_literal_root_role_sets(DEFAULT_SANDBOX_ROOT_REGISTRY) == {}


def test_production_sandbox_root_registry_callers_stay_on_current_root_owner() -> None:
    calls, definitions = _attribute_calls_and_definitions(ROLE_NAMED_ROOT_APIS)
    caller_paths = {
        relpath
        for _name, relpath, _scope in calls
        if relpath.startswith("tools/install_sandbox/")
        and relpath != "tools/install_sandbox/harness_specs.py"
    }

    production_definitions = {
        definition for definition in definitions if definition[1].startswith("tools/install_sandbox/")
    }

    assert caller_paths == PRODUCTION_ROOT_REGISTRY_CALLERS
    assert production_definitions == {
        ("env_entries", "tools/install_sandbox/harness_specs.py"),
        ("env_roots", "tools/install_sandbox/harness_specs.py"),
        ("install_surface_root_names", "tools/install_sandbox/harness_specs.py"),
        ("policy_cwd_root_names", "tools/install_sandbox/harness_specs.py"),
        ("preflight_roots", "tools/install_sandbox/harness_specs.py"),
        ("reset_roots", "tools/install_sandbox/harness_specs.py"),
        ("root_names", "tools/install_sandbox/harness_specs.py"),
        ("runtime_paths", "tools/install_sandbox/harness_specs.py"),
        ("sandbox_path_assertion_roots", "tools/install_sandbox/harness_specs.py"),
        ("scenario_root_names", "tools/install_sandbox/harness_specs.py"),
        ("scenario_root_paths", "tools/install_sandbox/harness_specs.py"),
        ("volume_roots", "tools/install_sandbox/harness_specs.py"),
    }
