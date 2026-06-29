from __future__ import annotations

from tools.install_sandbox.targets import install_target_catalog, install_target_models


def scope(relative: str = "graphify.txt") -> install_target_models.ScopeSpec:
    return install_target_models.ScopeSpec(
        install_command=("graphify", "install"),
        uninstall_command=("graphify", "uninstall"),
        cwd_root="project",
        expected=(install_target_models.InstallSurface("project", relative),),
    )


def planner_registry() -> install_target_catalog.ScenarioRegistry:
    return install_target_catalog.ScenarioRegistry(
        {
            "claude": install_target_models.PlatformSpec(
                name="claude",
                scopes={"project": scope("claude.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "codex": install_target_models.PlatformSpec(
                name="codex",
                scopes={"project": scope("codex.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "cursor": install_target_models.PlatformSpec(
                name="cursor",
                scopes={"project": scope("cursor.txt")},
                unsupported_scopes={"user": "user install is not supported"},
            ),
            "gemini": install_target_models.PlatformSpec(
                name="gemini",
                scopes={"project": scope("gemini.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "windows": install_target_models.PlatformSpec(
                name="windows",
                scopes={"project": scope("windows.txt")},
                simulated_linux_layout=True,
            ),
        }
    )
