"""Host-side Docker build and isolated container execution."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGE = "graphify-install-sandbox-v8:local"
BUILD_TIMEOUT_SECONDS = 900
RUN_TIMEOUT_SECONDS = 7200

CONTAINER_REPO = "/mnt/graphify-repo"
CONTAINER_OUTPUT = "/sandbox-out"
CONTAINER_HOME = "/tmp/graphify-home"
CONTAINER_XDG = "/tmp/graphify-xdg"
CONTAINER_PROJECT = "/tmp/graphify-project"
CONTAINER_USER_CWD = "/tmp/graphify-user-cwd"
CONTAINER_SOURCE = "/tmp/graphify-source"


def build_image_command(runtime: str, image: str) -> list[str]:
    return [runtime, "build", "--tag", image, str(HARNESS_DIR)]


def build_run_command(
    *,
    runtime: str,
    image: str,
    repo: Path,
    output: Path,
    target: str | None,
    all_targets: bool,
    scope: str,
) -> list[str]:
    if bool(target) == bool(all_targets):
        raise ValueError("select exactly one target mode")
    command = [runtime, "run", "--rm"]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key, value in {
        "HOME": CONTAINER_HOME,
        "XDG_CONFIG_HOME": CONTAINER_XDG,
        "GRAPHIFY_SANDBOX_REPO": CONTAINER_REPO,
        "GRAPHIFY_SANDBOX_OUTPUT": CONTAINER_OUTPUT,
        "GRAPHIFY_SANDBOX_PROJECT": CONTAINER_PROJECT,
        "GRAPHIFY_SANDBOX_USER_CWD": CONTAINER_USER_CWD,
        "GRAPHIFY_SANDBOX_SOURCE": CONTAINER_SOURCE,
    }.items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(
        [
            "--volume",
            f"{repo}:{CONTAINER_REPO}:ro",
            "--volume",
            f"{output}:{CONTAINER_OUTPUT}:rw",
            "--workdir",
            CONTAINER_PROJECT,
            image,
            "--scope",
            scope,
        ]
    )
    if all_targets:
        command.append("--all")
    else:
        command.extend(["--target", str(target)])
    return command


def _run(argv: list[str], timeout: int) -> int:
    print(f"$ {shlex.join(argv)}", flush=True)
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"error: container runtime not found: {argv[0]}", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(
            f"error: command timed out after {timeout} seconds: {shlex.join(argv)}",
            file=sys.stderr,
        )
        return 124
    return completed.returncode


def run_sandbox(
    *,
    repo: Path,
    output: Path,
    target: str | None,
    all_targets: bool,
    scope: str,
    runtime: str = "docker",
    image: str = DEFAULT_IMAGE,
) -> int:
    output.mkdir(parents=True, exist_ok=True)
    build = _run(build_image_command(runtime, image), BUILD_TIMEOUT_SECONDS)
    if build:
        return build
    return _run(
        build_run_command(
            runtime=runtime,
            image=image,
            repo=repo,
            output=output,
            target=target,
            all_targets=all_targets,
            scope=scope,
        ),
        RUN_TIMEOUT_SECONDS,
    )

