from __future__ import annotations

import json
import os
import subprocess

import pytest

from tools.install_sandbox.runtime import source_snapshot


def snapshot_config(repo, src) -> source_snapshot.SourceSnapshotConfig:
    return source_snapshot.SourceSnapshotConfig(repo_mount=repo, src=src)


def init_git_repo(repo) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def git_add(repo, *paths: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_source_excludes_nested_sandbox_out() -> None:
    assert source_snapshot.should_exclude_source_path(".kilo/plans/private.md")
    assert source_snapshot.should_exclude_source_path("tools/install_sandbox/out")
    assert source_snapshot.should_exclude_source_path("tools/install_sandbox/out/codex/manifest.json")
    assert source_snapshot.should_exclude_source_path("graphifyy.egg-info/PKG-INFO")
    assert not source_snapshot.should_exclude_source_path("tools/install_sandbox/sandbox_runner.py")


def test_package_provenance_parsing(tmp_path) -> None:
    source = tmp_path / "graphify-src"
    site = tmp_path / "site-packages"
    dist_info = site / "graphifyy-1.2.3.dist-info"
    source.mkdir()
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Name: graphifyy\nVersion: 1.2.3\n", encoding="utf-8")
    (dist_info / "direct_url.json").write_text(json.dumps({"url": source.resolve().as_uri(), "dir_info": {}}), encoding="utf-8")

    metadata = source_snapshot.read_installed_package_metadata("graphifyy", source, [site])

    assert metadata["package_name"] == "graphifyy"
    assert metadata["version"] == "1.2.3"
    assert str(metadata["location"]).endswith("site-packages")
    assert metadata["installed_from_copied_source"] is True


def test_source_manifest_prunes_directories_and_hashes_key_files(tmp_path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "pyproject.toml").write_text("[project]\nname = 'graphifyy'\n", encoding="utf-8")
    (src / "graphify").mkdir()
    (src / "graphify" / "__main__.py").write_text("print('graphify')\n", encoding="utf-8")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    config = source_snapshot.SourceSnapshotConfig(repo_mount=tmp_path / "repo", src=src)

    manifest = source_snapshot.source_manifest(src, config)

    files = {entry["path"]: entry for entry in manifest["files_sample"]}
    assert manifest["file_count"] == 2
    assert "pyproject.toml" in files
    assert "graphify/__main__.py" in files
    assert "sha256" in files["pyproject.toml"]
    assert "sha256" in files["graphify/__main__.py"]
    assert "node_modules/ignored.js" not in files


def test_tracked_source_copy_preserves_safe_in_repo_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("target.txt")
    init_git_repo(repo)
    git_add(repo, "target.txt", "link.txt")

    manifest = source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))

    assert manifest is not None
    assert manifest["snapshot_strategy"] == "git_tracked_files"
    assert (src / "link.txt").is_symlink()
    assert os.readlink(src / "link.txt") == "target.txt"


def test_fallback_source_copy_preserves_safe_in_repo_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("target.txt")

    manifest = source_snapshot.copy_source_tree("always", config=snapshot_config(repo, src))

    assert manifest["snapshot_strategy"] == "copytree_with_exclusions"
    assert (src / "link.txt").is_symlink()
    assert os.readlink(src / "link.txt") == "target.txt"


def test_tracked_source_copy_rejects_symlink_to_untracked_in_repo_target(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("target.txt")
    init_git_repo(repo)
    git_add(repo, "link.txt")

    with pytest.raises(RuntimeError, match="absent from source snapshot"):
        source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))


def test_tracked_source_copy_rejects_symlink_to_untracked_intermediate_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "middle.txt").symlink_to("target.txt")
    (repo / "link.txt").symlink_to("middle.txt")
    init_git_repo(repo)
    git_add(repo, "target.txt", "link.txt")

    with pytest.raises(RuntimeError, match="absent from source snapshot"):
        source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))

    assert not (src / "link.txt").exists()


def test_tracked_source_copy_rejects_symlink_to_excluded_in_repo_target(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "dist").mkdir()
    (repo / "dist" / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("dist/target.txt")
    init_git_repo(repo)
    git_add(repo, "dist/target.txt", "link.txt")

    with pytest.raises(RuntimeError, match="absent from source snapshot"):
        source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))


def test_tracked_source_copy_rejects_out_of_repo_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("../outside.txt")
    init_git_repo(repo)
    git_add(repo, "link.txt")

    with pytest.raises(RuntimeError, match="outside repository"):
        source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))


def test_tracked_source_copy_rejects_missing_in_repo_target(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "link.txt").symlink_to("missing.txt")
    init_git_repo(repo)
    git_add(repo, "link.txt")

    with pytest.raises(RuntimeError, match="missing target"):
        source_snapshot.copy_tracked_source_tree(snapshot_config(repo, src))


def test_fallback_source_copy_rejects_out_of_repo_symlink(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("../outside.txt")

    with pytest.raises(RuntimeError, match="outside repository"):
        source_snapshot.copy_source_tree("always", config=snapshot_config(repo, src))


def test_fallback_source_copy_rejects_symlink_to_excluded_in_repo_target(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "dist").mkdir()
    (repo / "dist" / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "link.txt").symlink_to("dist/target.txt")

    with pytest.raises(RuntimeError, match="absent from source snapshot"):
        source_snapshot.copy_source_tree("always", config=snapshot_config(repo, src))

    assert not (src / "link.txt").exists()


def test_fallback_source_copy_rejects_symlink_through_excluded_intermediate(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = tmp_path / "src"
    repo.mkdir()
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    (repo / "dist").mkdir()
    (repo / "dist" / "middle.txt").symlink_to("../target.txt")
    (repo / "link.txt").symlink_to("dist/middle.txt")

    with pytest.raises(RuntimeError, match="absent from source snapshot"):
        source_snapshot.copy_source_tree("always", config=snapshot_config(repo, src))

    assert not (src / "link.txt").exists()
