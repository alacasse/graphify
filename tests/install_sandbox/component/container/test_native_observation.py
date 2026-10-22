"""Filesystem observations have their own inputs, independent of expectations."""

from pathlib import Path

import pytest

from tools.install_sandbox.container.environment import ObservedEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter


def observed(root: Path) -> ObservedEnvironment:
    environment = ObservedEnvironment()
    environment.home = root / "home"
    environment.project = root / "project"
    environment.home.mkdir()
    environment.project.mkdir()
    return environment


def test_snapshot_retains_binary_bytes_and_complete_nested_inventory(tmp_path: Path) -> None:
    environment = observed(tmp_path)
    (environment.project / "nested").mkdir()
    (environment.project / "nested/data").write_bytes(b"\x00original\xff")
    snapshot = environment.observe(ResultWriter(tmp_path / "proof"), "before")
    (environment.project / "nested/data").write_bytes(b"later")
    assert snapshot.contents == {("project", "nested/data"): b"\x00original\xff"}
    assert snapshot.absent("project", "nested/missing")
    assert not snapshot.obstacles


def test_symlink_is_obstacle_and_never_followed(tmp_path: Path) -> None:
    environment = observed(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "private").write_bytes(b"must not be read")
    (environment.home / "linked").symlink_to(external, target_is_directory=True)
    snapshot = environment.observe(ResultWriter(tmp_path / "proof"), "after")
    assert not snapshot.contents
    assert snapshot.obstacles[0]["path"] == "linked"
    assert snapshot.entry("home", "linked/private") is None


def test_failed_inventory_does_not_prove_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = observed(tmp_path)
    original = Path.iterdir

    def denied(path: Path):
        if path == environment.home:
            raise PermissionError("Synthetic inventory refusal")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    snapshot = environment.observe(ResultWriter(tmp_path / "proof"), "before")
    assert not snapshot.absent("home", "missing")
    assert snapshot.obstacles[0]["operation"] == "list_directory"
