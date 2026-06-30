from __future__ import annotations

import ast
from pathlib import Path

from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_ALIAS_NAMES = {"scenario_roots"}
ROLE_NAMED_ROOT_APIS = {
    "env_roots",
    "install_surface_root_names",
    "policy_cwd_root_names",
    "root_names",
    "scenario_root_paths",
}


def _sandbox_python_files() -> list[Path]:
    return sorted(
        [
            *Path("tools/install_sandbox").glob("**/*.py"),
            *Path("tests/install_sandbox").glob("**/*.py"),
        ]
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


def test_default_sandbox_root_registry_characterizes_current_role_groups() -> None:
    registry = DEFAULT_SANDBOX_ROOT_REGISTRY

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
    assert registry.scenario_root_paths(registry.runtime_paths()) == registry.scenario_roots(registry.runtime_paths())
    assert tuple(registry.scenario_roots(registry.runtime_paths())) == ("home", "project", "user_cwd")
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


def test_scenario_root_alias_callers_are_temporary_test_evidence_only() -> None:
    calls, definitions = _attribute_calls_and_definitions(SANDBOX_ALIAS_NAMES)

    assert definitions == {
        ("scenario_roots", "tools/install_sandbox/harness_specs.py"),
    }
    assert calls == {
        (
            "scenario_roots",
            "tests/install_sandbox/test_harness_specs.py",
            "test_default_sandbox_root_registry_characterizes_current_role_groups",
        ),
    }


def test_production_sandbox_root_callers_use_role_named_apis() -> None:
    calls, _definitions = _attribute_calls_and_definitions(ROLE_NAMED_ROOT_APIS)
    production_calls = {name for name, relpath, _scope in calls if relpath.startswith("tools/install_sandbox/")}

    assert ROLE_NAMED_ROOT_APIS <= production_calls
