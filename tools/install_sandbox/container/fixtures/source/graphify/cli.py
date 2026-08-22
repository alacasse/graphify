"""Deterministic fictional public Graphify command."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path


def _owned_path(*, project: bool) -> Path:
    base = Path.cwd() if project else Path(os.environ["HOME"])
    return base / ".fictional" / ("project.txt" if project else "user.txt")


def _install(*, project: bool) -> None:
    source = (
        Path(__file__).resolve().parent / "fixtures" / ("project.txt" if project else "user.txt")
    )
    destination = _owned_path(project=project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _remove(*, project: bool) -> None:
    destination = _owned_path(project=project)
    destination.unlink(missing_ok=True)
    with suppress(OSError):
        destination.parent.rmdir()


def main() -> int:
    arguments = sys.argv[1:]
    if arguments == ["--version"]:
        print("graphify-fictional 1.0.0")
        return 0
    if arguments == ["install", "--list"]:
        print("fictional")
        return 0
    if not arguments:
        return 2
    command, *options = arguments
    project = "--project" in options
    if command == "install" and "--platform" in options:
        _install(project=project)
        return 0
    if command != "uninstall":
        return 2
    if "--purge" in options:
        _remove(project=False)
        _remove(project=True)
        output = Path.cwd() / "graphify-out"
        if output.exists():
            shutil.rmtree(output)
        return 0
    _remove(project=project)
    return 0
