from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from ..sandbox_roots import DEFAULT_SANDBOX_ROOT_REGISTRY


HARNESS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "graphify-install-sandbox:local"
ROOT_REGISTRY = DEFAULT_SANDBOX_ROOT_REGISTRY
CONTAINER_REPO = ROOT_REGISTRY.container_path("repo_mount")
CONTAINER_OUTPUT = ROOT_REGISTRY.container_path("output")
CONTAINER_HOME = ROOT_REGISTRY.container_path("home")
CONTAINER_XDG = ROOT_REGISTRY.container_path("xdg_config_home")
CONTAINER_PROJECT = ROOT_REGISTRY.container_path("project")
CONTAINER_SRC = ROOT_REGISTRY.container_path("src")
BUILD_TIMEOUT_SECONDS = 600
RUN_TIMEOUT_SECONDS = 3600


def shell_join(command: list[str]) -> str:
    return shlex.join(command)


def build_image_command(runtime: str, image: str) -> list[str]:
    return [runtime, "build", "-t", image, str(HARNESS_DIR)]


def build_container_command(
    *,
    runtime: str,
    image: str,
    repo: Path,
    output: Path,
    platform: str | None,
    all_platforms: bool,
    scope: str,
    copy_source: str,
    keep_container: bool,
) -> list[str]:
    command = [runtime, "run"]
    if not keep_container:
        command.append("--rm")
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key, value in ROOT_REGISTRY.env_entries().items():
        command.extend(["--env", f"{key}={value}"])
    host_paths = {"repo_mount": repo, "output": output}
    for root in ROOT_REGISTRY.volume_roots():
        host_path = host_paths[root.name]
        command.extend(["--volume", f"{host_path}:{root.container_path}:{root.mount_mode}"])
    command.extend(
        [
            "--workdir",
            CONTAINER_PROJECT,
            image,
            "--scope",
            scope,
            "--copy-source",
            copy_source,
        ]
    )
    if all_platforms:
        command.append("--all")
    elif platform:
        command.extend(["--platform", platform])
    else:
        raise ValueError("either platform or all_platforms is required")
    return command


def run_command(command: list[str], *, timeout_seconds: int, command_class: str) -> None:
    print(f"$ {shell_join(command)}", flush=True)
    try:
        subprocess.run(command, check=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        print(f"error: {command_class} command timed out after {timeout_seconds} seconds: {shell_join(command)}", file=sys.stderr)
        raise SystemExit(124) from exc
