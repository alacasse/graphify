from __future__ import annotations

from pathlib import Path
from typing import Mapping

try:
    from ..expected_effects import InstallSurface
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import InstallSurface  # type: ignore[no-redef]


def resolve_install_root(root: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def resolve_install_surface_path(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    return resolve_install_root(surface.root, roots) / surface.relative
