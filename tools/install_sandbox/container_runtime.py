from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGE = "graphify-install-sandbox:local"
CONTAINER_REPO = "/mnt/graphify-repo"
CONTAINER_OUTPUT = "/sandbox-out"
CONTAINER_HOME = "/tmp/graphify-home"
CONTAINER_XDG = "/tmp/graphify-home/.config"
CONTAINER_PROJECT = "/tmp/graphify-project"
BUILD_TIMEOUT_SECONDS = 600
RUN_TIMEOUT_SECONDS = 3600


def shell_join(command: list[str]) -> str:
    return shlex.join(command)


class ContainerRuntimeAdapter:
    def __init__(self, *, runtime: str, image: str) -> None:
        self.runtime = runtime
        self.image = image

    def build_image_command(self) -> list[str]:
        return build_image_command(self.runtime, self.image)

    def build_container_command(
        self,
        *,
        repo: Path,
        output: Path,
        platform: str | None,
        all_platforms: bool,
        scope: str,
        copy_source: str,
        keep_container: bool,
    ) -> list[str]:
        return build_container_command(
            runtime=self.runtime,
            image=self.image,
            repo=repo,
            output=output,
            platform=platform,
            all_platforms=all_platforms,
            scope=scope,
            copy_source=copy_source,
            keep_container=keep_container,
        )

    def run_command(self, command: list[str], *, timeout_seconds: int, command_class: str) -> None:
        run_command(command, timeout_seconds=timeout_seconds, command_class=command_class)


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
    command.extend(
        [
            "--env",
            f"HOME={CONTAINER_HOME}",
            "--env",
            f"XDG_CONFIG_HOME={CONTAINER_XDG}",
            "--env",
            f"GRAPHIFY_PROJECT={CONTAINER_PROJECT}",
            "--env",
            f"GRAPHIFY_REPO_MOUNT={CONTAINER_REPO}",
            "--env",
            "GRAPHIFY_SRC=/tmp/graphify-src",
            "--env",
            f"GRAPHIFY_OUTPUT={CONTAINER_OUTPUT}",
            "--volume",
            f"{repo}:{CONTAINER_REPO}:ro",
            "--volume",
            f"{output}:{CONTAINER_OUTPUT}:rw",
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
