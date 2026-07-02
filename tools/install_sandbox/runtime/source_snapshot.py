from __future__ import annotations

import fnmatch
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PACKAGE_NAME = "graphifyy"

COPY_EXCLUDES = (
    ".git",
    ".kilo",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "graphify-out",
    "sandbox-out",
    "tools/install_sandbox/out",
    "build",
    "dist",
    "*.egg-info",
)
MANIFEST_PRUNE_DIRS = {".local", ".cache", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


@dataclass(frozen=True)
class SourceSnapshotConfig:
    repo_mount: Path
    src: Path
    copy_excludes: tuple[str, ...] = COPY_EXCLUDES
    manifest_prune_dirs: frozenset[str] = frozenset(MANIFEST_PRUNE_DIRS)
    package_name: str = PACKAGE_NAME
    home: Path | None = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def should_exclude_source_path(relative: str, patterns: Iterable[str] = COPY_EXCLUDES) -> bool:
    parts = Path(relative).parts
    for pattern in patterns:
        if "/" in pattern:
            if relative == pattern or relative.startswith(f"{pattern}/"):
                return True
        elif fnmatch.fnmatch(Path(relative).name, pattern) or any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def copy_source_ignore(directory: str, names: list[str], config: SourceSnapshotConfig) -> set[str]:
    base = Path(directory)
    ignored = set()
    for name in names:
        path = base / name
        try:
            relative = path.relative_to(config.repo_mount).as_posix()
        except ValueError:
            relative = name
        if should_exclude_source_path(relative, config.copy_excludes):
            ignored.add(name)
    return ignored


def repo_relative(path: Path, config: SourceSnapshotConfig) -> str:
    try:
        return path.relative_to(config.repo_mount).as_posix()
    except ValueError:
        return path.name


def copied_paths_contain(relative: str, copied_paths: set[str]) -> bool:
    return relative in copied_paths or any(path.startswith(f"{relative}/") for path in copied_paths)


def required_snapshot_paths_for_symlink_target(src_path: Path, target_path: Path, config: SourceSnapshotConfig) -> list[str]:
    repo = config.repo_mount.resolve()
    current = Path(os.path.abspath(os.path.normpath(src_path.parent / target_path)))
    try:
        parts = list(current.relative_to(repo).parts)
    except ValueError:
        return []

    required: list[str] = []
    seen_symlinks: set[str] = set()
    for _ in range(40):
        if not parts:
            return required
        candidate = repo
        for index, part in enumerate(parts):
            candidate = candidate / part
            relative = candidate.relative_to(repo).as_posix()
            required.append(relative)
            if candidate.is_symlink():
                if relative in seen_symlinks:
                    return required
                seen_symlinks.add(relative)
                symlink_target = Path(os.readlink(candidate))
                next_path = symlink_target if symlink_target.is_absolute() else candidate.parent / symlink_target
                next_path = Path(os.path.abspath(os.path.normpath(next_path)))
                try:
                    parts = list(next_path.relative_to(repo).parts) + parts[index + 1 :]
                except ValueError:
                    return required
                break
        else:
            return required
    return required


def validate_source_symlink(src_path: Path, config: SourceSnapshotConfig, *, copied_paths: set[str] | None = None) -> str:
    target = os.readlink(src_path)
    target_path = Path(target)
    if target_path.is_absolute():
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path, config)} points to absolute target {target}")
    resolved_repo = config.repo_mount.resolve()
    resolved_target = (src_path.parent / target_path).resolve(strict=False)
    try:
        target_relative = resolved_target.relative_to(resolved_repo).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path, config)} points outside repository to {target}") from exc
    if not resolved_target.exists():
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path, config)} points to missing target {target}")
    if should_exclude_source_path(target_relative, config.copy_excludes):
        raise RuntimeError(
            f"unsafe source symlink: {repo_relative(src_path, config)} points to target absent from source snapshot: {target}"
        )
    if copied_paths is not None and not copied_paths_contain(target_relative, copied_paths):
        raise RuntimeError(
            f"unsafe source symlink: {repo_relative(src_path, config)} points to target absent from source snapshot: {target}"
        )
    if copied_paths is not None:
        for required_relative in required_snapshot_paths_for_symlink_target(src_path, target_path, config):
            if not copied_paths_contain(required_relative, copied_paths):
                raise RuntimeError(
                    f"unsafe source symlink: {repo_relative(src_path, config)} "
                    f"points to target absent from source snapshot: {target}"
                )
    return target


def validate_source_symlinks_for_copytree(config: SourceSnapshotConfig) -> None:
    copied_paths: set[str] = set()
    symlink_paths: list[Path] = []
    for root, dirs, files in os.walk(config.repo_mount):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for name in sorted(dirs):
            path = root_path / name
            relative = repo_relative(path, config)
            if should_exclude_source_path(relative, config.copy_excludes):
                continue
            copied_paths.add(relative)
            if path.is_symlink():
                symlink_paths.append(path)
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in sorted(files):
            path = root_path / name
            relative = repo_relative(path, config)
            if should_exclude_source_path(relative, config.copy_excludes):
                continue
            copied_paths.add(relative)
            if path.is_symlink():
                symlink_paths.append(path)
    for path in symlink_paths:
        validate_source_symlink(path, config, copied_paths=copied_paths)


def pruned_file_walk(base: Path, prune_dirs: Iterable[str] = MANIFEST_PRUNE_DIRS) -> Iterable[Path]:
    if not base.exists():
        return
    prune = set(prune_dirs)
    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in prune)
        for name in sorted(files):
            yield root_path / name


def source_manifest(src: Path, config: SourceSnapshotConfig) -> dict[str, object]:
    files: list[dict[str, object]] = []
    file_count = 0
    for path in pruned_file_walk(src, config.manifest_prune_dirs):
        file_count += 1
        rel = path.relative_to(src).as_posix()
        if len(files) < 5000:
            entry = {"path": rel, "size": path.stat().st_size}
            if rel in ("pyproject.toml", "graphify/__main__.py"):
                entry["sha256"] = sha256(path)
            files.append(entry)
    return {"root": str(src), "file_count": file_count, "files_sample": files, "excluded_patterns": list(config.copy_excludes)}


def copy_tracked_source_tree(config: SourceSnapshotConfig) -> dict[str, object] | None:
    result = subprocess.run(["git", "-C", str(config.repo_mount), "ls-files", "-z"], text=False, capture_output=True)
    if result.returncode != 0:
        return None
    config.src.mkdir(parents=True, exist_ok=True)
    tracked_paths = {
        raw.decode("utf-8", errors="surrogateescape")
        for raw in result.stdout.split(b"\0")
        if raw and not should_exclude_source_path(raw.decode("utf-8", errors="surrogateescape"), config.copy_excludes)
    }
    copied = 0
    for rel in sorted(tracked_paths):
        src_path = config.repo_mount / rel
        dst_path = config.src / rel
        if src_path.is_symlink():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.symlink_to(validate_source_symlink(src_path, config, copied_paths=tracked_paths))
            copied += 1
        elif src_path.is_file():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied += 1
    manifest = source_manifest(config.src, config)
    manifest["copy_source_mode"] = "auto"
    manifest["snapshot_strategy"] = "git_tracked_files"
    manifest["copied_tracked_file_count"] = copied
    return manifest


def copy_source_tree(copy_source: str = "always", *, config: SourceSnapshotConfig) -> dict[str, object]:
    if config.src.exists():
        shutil.rmtree(config.src)
    if copy_source == "auto":
        tracked = copy_tracked_source_tree(config)
        if tracked is not None:
            return tracked
    validate_source_symlinks_for_copytree(config)
    shutil.copytree(config.repo_mount, config.src, symlinks=True, ignore=lambda directory, names: copy_source_ignore(directory, names, config))
    manifest = source_manifest(config.src, config)
    manifest["copy_source_mode"] = copy_source
    manifest["snapshot_strategy"] = "copytree_with_exclusions"
    return manifest


def package_search_paths(home: Path | None = None) -> list[Path]:
    paths = [Path(path) for path in sys.path if path]
    if home is not None:
        paths.extend(home.glob(".local/lib/python*/site-packages"))
    return list(dict.fromkeys(path for path in paths if path.exists()))


def direct_url_source_path(direct_url: dict[str, object] | None) -> Path | None:
    if not direct_url:
        return None
    url = direct_url.get("url")
    if not isinstance(url, str):
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "file":
        return None
    return Path(urllib.parse.unquote(parsed.path)).resolve()


def package_metadata_value(metadata: importlib.metadata.PackageMetadata, key: str) -> str | None:
    try:
        value = metadata[key]
    except KeyError:
        return None
    return value or None


def dist_to_metadata(dist: importlib.metadata.Distribution, source: Path, package_name: str = PACKAGE_NAME) -> dict[str, object]:
    direct_url = None
    direct_text = dist.read_text("direct_url.json")
    if direct_text:
        direct_url = json.loads(direct_text)
    source_path = direct_url_source_path(direct_url)
    return {
        "package_name": package_metadata_value(dist.metadata, "Name") or package_name,
        "version": dist.version,
        "location": str(Path(str(dist.locate_file(""))).resolve()),
        "direct_url": direct_url,
        "installed_from_copied_source": source_path == source.resolve(),
    }


def metadata_from_dist_info(dist_info: Path, source: Path, package_name: str = PACKAGE_NAME) -> dict[str, object] | None:
    metadata_path = dist_info / "METADATA"
    if not metadata_path.exists():
        return None
    name = None
    version = None
    for line in metadata_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Name: "):
            name = line.split(": ", 1)[1].strip()
        if line.startswith("Version: "):
            version = line.split(": ", 1)[1].strip()
    if name != package_name or not version:
        return None
    direct_url = None
    direct_url_path = dist_info / "direct_url.json"
    if direct_url_path.exists():
        direct_url = json.loads(direct_url_path.read_text(encoding="utf-8"))
    source_path = direct_url_source_path(direct_url)
    return {
        "package_name": name,
        "version": version,
        "location": str(dist_info.parent.resolve()),
        "direct_url": direct_url,
        "installed_from_copied_source": source_path == source.resolve(),
    }


def read_installed_package_metadata(package_name: str, source: Path, search_paths: list[Path] | None = None, *, home: Path | None = None) -> dict[str, object]:
    if search_paths is None:
        try:
            return dist_to_metadata(importlib.metadata.distribution(package_name), source, package_name)
        except importlib.metadata.PackageNotFoundError:
            pass

    paths = search_paths or package_search_paths(home)
    for search_path in paths:
        for dist in importlib.metadata.distributions(path=[str(search_path)]):
            if (package_metadata_value(dist.metadata, "Name") or "").lower() == package_name.lower():
                return dist_to_metadata(dist, source, package_name)

    for search_path in paths:
        for dist_info in search_path.glob(f"{package_name}-*.dist-info"):
            metadata = metadata_from_dist_info(dist_info, source, package_name)
            if metadata:
                return metadata

    return {
        "package_name": package_name,
        "version": None,
        "location": None,
        "direct_url": None,
        "installed_from_copied_source": False,
    }
