from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxRootSpec:
    name: str
    container_path: str
    env_var: str | None = None
    reset: bool = False
    preflight_required: bool = False
    mount_mode: str | None = None
    sandbox_path_required: str | None = None
    preserve_children: tuple[str, ...] = ()


@dataclass(frozen=True)
class SandboxRootRegistry:
    roots: tuple[SandboxRootSpec, ...]

    def spec(self, name: str) -> SandboxRootSpec:
        for root in self.roots:
            if root.name == name:
                return root
        raise KeyError(name)

    def container_path(self, name: str) -> str:
        return self.spec(name).container_path

    def runtime_path(self, name: str, environ: dict[str, str] | None = None) -> Path:
        spec = self.spec(name)
        values = os.environ if environ is None else environ
        return Path(values.get(spec.env_var, spec.container_path)) if spec.env_var else Path(spec.container_path)

    def runtime_paths(self, environ: dict[str, str] | None = None) -> dict[str, Path]:
        return {root.name: self.runtime_path(root.name, environ) for root in self.roots}

    def scenario_roots(self, paths: dict[str, Path]) -> dict[str, Path]:
        return {name: paths[name] for name in ("home", "project", "user_cwd")}

    def env_entries(self) -> dict[str, str]:
        return {root.env_var: root.container_path for root in self.roots if root.env_var is not None}

    def volume_roots(self) -> tuple[SandboxRootSpec, ...]:
        return tuple(root for root in self.roots if root.mount_mode is not None)

    def reset_roots(self) -> tuple[SandboxRootSpec, ...]:
        return tuple(root for root in self.roots if root.reset)

    def preflight_roots(self) -> tuple[SandboxRootSpec, ...]:
        return tuple(root for root in self.roots if root.preflight_required)

    def declared_expected_root_names(self) -> set[str]:
        return {"home", "project", "user_cwd"}


DEFAULT_SANDBOX_ROOT_REGISTRY = SandboxRootRegistry(
    (
        SandboxRootSpec("home", "/tmp/graphify-home", env_var="HOME", reset=True, preflight_required=True, sandbox_path_required="/tmp/graphify-home", preserve_children=(".local",)),
        SandboxRootSpec("xdg_config_home", "/tmp/graphify-home/.config", env_var="XDG_CONFIG_HOME", preflight_required=True, sandbox_path_required="/tmp/graphify-home/.config"),
        SandboxRootSpec("project", "/tmp/graphify-project", env_var="GRAPHIFY_PROJECT", reset=True, preflight_required=True, sandbox_path_required="/tmp/graphify-project"),
        SandboxRootSpec("user_cwd", "/tmp/graphify-user-cwd", reset=True),
        SandboxRootSpec("repo_mount", "/mnt/graphify-repo", env_var="GRAPHIFY_REPO_MOUNT", preflight_required=True, mount_mode="ro"),
        SandboxRootSpec("src", "/tmp/graphify-src", env_var="GRAPHIFY_SRC"),
        SandboxRootSpec("output", "/sandbox-out", env_var="GRAPHIFY_OUTPUT", mount_mode="rw"),
    )
)
