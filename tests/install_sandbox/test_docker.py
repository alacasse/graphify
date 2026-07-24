from pathlib import Path

import pytest

from tools.install_sandbox.docker import (
    CONTAINER_HOME,
    CONTAINER_OUTPUT,
    CONTAINER_PROJECT,
    CONTAINER_REPO,
    CONTAINER_SOURCE,
    CONTAINER_USER_CWD,
    CONTAINER_XDG,
    build_image_command,
    build_run_command,
)
from tools.install_sandbox.sandbox_runner import HARNESS_SPEC_DIR
from tools.install_sandbox.specs import load_catalog


def test_docker_commands_mount_source_read_only_and_isolate_every_root(tmp_path):
    repo = tmp_path / "repo"
    output = tmp_path / "output"
    command = build_run_command(
        runtime="docker",
        image="sandbox:test",
        repo=repo,
        output=output,
        target="codex",
        all_targets=False,
        scope="project",
    )

    assert build_image_command("docker", "sandbox:test")[:4] == [
        "docker",
        "build",
        "--tag",
        "sandbox:test",
    ]
    assert f"{repo}:{CONTAINER_REPO}:ro" in command
    assert f"{output}:{CONTAINER_OUTPUT}:rw" in command
    for path in {
        CONTAINER_HOME,
        CONTAINER_XDG,
        CONTAINER_PROJECT,
        CONTAINER_USER_CWD,
        CONTAINER_SOURCE,
        CONTAINER_REPO,
        CONTAINER_OUTPUT,
    }:
        assert path in " ".join(command)
    assert len(
        {
            CONTAINER_HOME,
            CONTAINER_XDG,
            CONTAINER_PROJECT,
            CONTAINER_USER_CWD,
            CONTAINER_SOURCE,
            CONTAINER_REPO,
            CONTAINER_OUTPUT,
        }
    ) == 7
    assert command[-4:] == ["--scope", "project", "--target", "codex"]


def test_docker_command_requires_exactly_one_selection(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        build_run_command(
            runtime="docker",
            image="image",
            repo=tmp_path / "repo",
            output=tmp_path / "out",
            target=None,
            all_targets=False,
            scope="both",
        )


def test_container_oracle_is_packaged_with_harness_not_subject_repo(tmp_path):
    subject_specs = tmp_path / "tools" / "install_sandbox" / "specs"
    subject_specs.mkdir(parents=True)
    (subject_specs / "codex.yaml").write_text(
        "scopes: {}\n",
        encoding="utf-8",
    )

    catalog = load_catalog(HARNESS_SPEC_DIR)

    assert len(catalog) == 24
    assert HARNESS_SPEC_DIR.resolve() != subject_specs.resolve()
