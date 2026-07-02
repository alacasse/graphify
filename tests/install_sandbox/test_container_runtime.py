from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.runtime import container_runtime


def _option_values(command: list[str], option: str) -> list[str]:
    return [command[index + 1] for index, token in enumerate(command[:-1]) if token == option]


def test_docker_command_construction(tmp_path) -> None:
    repo = tmp_path / "repo"
    output = tmp_path / "out"
    repo.mkdir()
    output.mkdir()

    command = container_runtime.build_container_command(
        runtime="docker",
        image="graphify-install-sandbox:local",
        repo=repo,
        output=output,
        platform="codex",
        all_platforms=False,
        scope="both",
        copy_source="always",
        keep_container=False,
    )

    assert command[:2] == ["docker", "run"]
    assert "--rm" in command
    assert command.index("--rm") < command.index("--user")
    assert command[command.index("--user") + 1].count(":") == 1

    assert _option_values(command, "--env") == [
        f"{key}={value}" for key, value in container_runtime.ROOT_REGISTRY.env_entries().items()
    ]
    host_paths = {"repo_mount": repo, "output": output}
    assert _option_values(command, "--volume") == [
        f"{host_paths[root.name]}:{root.container_path}:{root.mount_mode}"
        for root in container_runtime.ROOT_REGISTRY.volume_roots()
    ]

    workdir_index = command.index("--workdir")
    assert command[workdir_index:] == [
        "--workdir",
        container_runtime.CONTAINER_PROJECT,
        "graphify-install-sandbox:local",
        "--scope",
        "both",
        "--copy-source",
        "always",
        "--platform",
        "codex",
    ]


def test_container_command_supports_all_platforms_without_rm(tmp_path) -> None:
    command = container_runtime.build_container_command(
        runtime="podman",
        image="custom-image",
        repo=tmp_path,
        output=tmp_path,
        platform=None,
        all_platforms=True,
        scope="project",
        copy_source="auto",
        keep_container=True,
    )

    assert command[:2] == ["podman", "run"]
    assert "--rm" not in command
    workdir_index = command.index("--workdir")
    assert command[workdir_index:] == [
        "--workdir",
        container_runtime.CONTAINER_PROJECT,
        "custom-image",
        "--scope",
        "project",
        "--copy-source",
        "auto",
        "--all",
    ]


def test_container_command_requires_platform_or_all_platforms(tmp_path) -> None:
    with pytest.raises(ValueError, match="either platform or all_platforms is required"):
        container_runtime.build_container_command(
            runtime="docker",
            image="image",
            repo=Path(tmp_path),
            output=Path(tmp_path),
            platform=None,
            all_platforms=False,
            scope="user",
            copy_source="always",
            keep_container=False,
        )


def test_build_image_command_uses_harness_directory() -> None:
    assert container_runtime.build_image_command("docker", "image") == [
        "docker",
        "build",
        "-t",
        "image",
        str(container_runtime.HARNESS_DIR),
    ]
    assert container_runtime.HARNESS_DIR.name == "install_sandbox"
    assert container_runtime.HARNESS_DIR.joinpath("Dockerfile").is_file()
