from __future__ import annotations

from pathlib import Path

from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY


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
    assert registry.declared_expected_root_names() == registry.install_surface_root_names()
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
