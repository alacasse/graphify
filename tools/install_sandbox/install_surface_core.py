from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    from .expected_effects import InstallSurface
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import InstallSurface  # type: ignore[no-redef]


@dataclass(frozen=True)
class InstallSurfaceStatus:
    path: Path
    ok: bool
    detail: str


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative


def expected_kind_status(path: Path, kind: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if kind == "file":
        return path.is_file(), "file" if path.is_file() else "expected_file_but_not_file"
    if kind == "dir":
        return path.is_dir(), "directory" if path.is_dir() else "expected_directory_but_not_directory"
    return True, "exists"


def install_surface_kind_status(surface: InstallSurface, roots: Mapping[str, Path]) -> InstallSurfaceStatus:
    path = resolve_install_surface_path(surface, roots)
    ok, detail = expected_kind_status(path, surface.kind)
    return InstallSurfaceStatus(path, ok, detail)
