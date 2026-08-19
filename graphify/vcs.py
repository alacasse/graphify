"""Validated version-control root discovery."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

_NON_GIT_MARKERS = (".hg", ".svn", "_darcs", ".fossil")


def _ancestors(start: Path) -> Iterator[Path]:
    current = start.resolve()
    home = Path.home().resolve()
    while True:
        yield current
        parent = current.parent
        if parent == current or current == home:
            return
        current = parent


def _git_confirms_root(candidate: Path) -> bool:
    """Ask Git whether *candidate* is the exact worktree root it represents."""

    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    rendered = result.stdout.strip()
    if not rendered or "\n" in rendered or "\x00" in rendered:
        return False
    try:
        return Path(rendered).resolve() == candidate
    except OSError:
        return False


def find_git_root(start: Path) -> Path | None:
    """Return the nearest Git-confirmed root, ignoring incomplete ``.git`` markers."""

    for candidate in _ancestors(start):
        if (candidate / ".git").exists() and _git_confirms_root(candidate):
            return candidate
    return None


def find_vcs_root(start: Path) -> Path | None:
    """Return the nearest confirmed Git or marker-backed non-Git VCS root."""

    for candidate in _ancestors(start):
        if (candidate / ".git").exists() and _git_confirms_root(candidate):
            return candidate
        if any((candidate / marker).exists() for marker in _NON_GIT_MARKERS):
            return candidate
    return None
