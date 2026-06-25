from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.runtime import container_runtime


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

    joined = " ".join(command)
    assert "--rm" in command
    assert "--user" in command
    assert "HOME=/tmp/graphify-home" in command
    assert "XDG_CONFIG_HOME=/tmp/graphify-home/.config" in command
    assert "GRAPHIFY_PROJECT=/tmp/graphify-project" in command
    assert f"{repo}:/mnt/graphify-repo:ro" in command
    assert f"{output}:/sandbox-out:rw" in command
    assert "--platform codex" in joined


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
    assert command[-3:] == ["--copy-source", "auto", "--all"]
    assert "custom-image" in command


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
