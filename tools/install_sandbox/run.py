#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from tools.install_sandbox.container_runtime import (
        BUILD_TIMEOUT_SECONDS,
        CONTAINER_HOME,
        CONTAINER_OUTPUT,
        CONTAINER_PROJECT,
        CONTAINER_REPO,
        CONTAINER_XDG,
        DEFAULT_IMAGE,
        HARNESS_DIR,
        RUN_TIMEOUT_SECONDS,
        build_container_command,
        build_image_command,
        run_command,
        shell_join,
    )
except ModuleNotFoundError:  # pragma: no cover - supports running this file directly from any cwd.
    from container_runtime import (  # type: ignore[no-redef]
        BUILD_TIMEOUT_SECONDS,
        CONTAINER_HOME,
        CONTAINER_OUTPUT,
        CONTAINER_PROJECT,
        CONTAINER_REPO,
        CONTAINER_XDG,
        DEFAULT_IMAGE,
        HARNESS_DIR,
        RUN_TIMEOUT_SECONDS,
        build_container_command,
        build_image_command,
        run_command,
        shell_join,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Graphify install scenarios in an isolated Docker sandbox.")
    parser.add_argument("--repo", required=True, type=Path, help="Path to the live Graphify working tree to mount read-only.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform", help="Platform to test from the harness scenario registry.")
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
        repo=repo,
        output=output,
        runtime=args.runtime,
        image=args.image,
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
        run_command(build_image_command(runtime=args.runtime, image=args.image), timeout_seconds=BUILD_TIMEOUT_SECONDS, command_class="docker_build")
    run_command(host_command, timeout_seconds=RUN_TIMEOUT_SECONDS, command_class="docker_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
