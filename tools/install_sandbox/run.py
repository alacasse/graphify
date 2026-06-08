#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


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


def run_command(command: list[str]) -> None:
    print(f"$ {shell_join(command)}", flush=True)
    subprocess.run(command, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Graphify install scenarios in an isolated Docker sandbox.")
    parser.add_argument("--repo", required=True, type=Path, help="Path to the live Graphify working tree to mount read-only.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform", help="Platform to test, for example codex.")
    target.add_argument("--all", action="store_true", help="Run the harness scenario registry.")
    parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
    parser.add_argument("--output", type=Path, default=Path("sandbox-out"), help="Artifact output directory.")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--no-build", action="store_true", help="Skip building the sandbox image.")
    parser.add_argument("--keep-container", action="store_true", help="Do not pass --rm to the container runtime.")
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--copy-source", choices=("always", "auto"), default="always")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo = args.repo.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not repo.is_dir():
        print(f"error: --repo does not exist or is not a directory: {repo}", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)

    host_command = build_container_command(
        runtime=args.runtime,
        image=args.image,
        repo=repo,
        output=output,
        platform=args.platform,
        all_platforms=args.all,
        scope=args.scope,
        copy_source=args.copy_source,
        keep_container=args.keep_container,
    )
    (output / "host-command.txt").write_text(shell_join(host_command) + "\n", encoding="utf-8")
    (output / "host-env.txt").write_text(
        "\n".join(
            [
                f"cwd={Path.cwd()}",
                f"repo={repo}",
                f"output={output}",
                f"runtime={args.runtime}",
                f"image={args.image}",
                f"host_home_mounted=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    if not args.no_build:
        run_command(build_image_command(args.runtime, args.image))
    run_command(host_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
