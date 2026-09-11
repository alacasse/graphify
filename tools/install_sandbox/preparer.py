"""Capture the candidate and the bounded sandbox payload for one image build."""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pathspec import GitIgnoreSpec

PAYLOAD = (
    "case.py",
    "spec.py",
    "driver.py",
    "environment.py",
    "results.py",
    "timings.py",
    "runner.py",
    "verifier.py",
    "container_main.py",
    "verify_preparation.py",
)


def prepare_context(subject: Path, directory: Path) -> Path:
    """Copy local changes once; callers must keep the candidate stable during capture."""
    context = directory / "context"
    context.mkdir()
    sandbox = Path(__file__).resolve().parent
    for filename in (
        *PAYLOAD,
        "prepare_dependencies.py",
        "Containerfile",
        "Containerfile.dockerignore",
    ):
        shutil.copyfile(sandbox / filename, context / filename)
    shutil.copytree(
        subject,
        context / "subject",
        symlinks=True,
        ignore=_SourceFilter(),
    )
    metadata = context / "metadata"
    metadata.mkdir()
    for filename in ("pyproject.toml", "uv.lock"):
        captured = context / "subject" / filename
        if captured.exists():
            shutil.copyfile(captured, metadata / filename)
    return context


class _SourceFilter:
    """Apply directory-local ignore rules during copytree's existing traversal."""

    def __init__(self) -> None:
        self.rules: dict[Path, tuple[tuple[Path, GitIgnoreSpec], ...]] = {}

    def __call__(self, directory: str, names: list[str]) -> set[str]:
        parent = Path(directory)
        rules = self.rules.get(parent.parent, ())
        ignore_file = parent / ".gitignore"
        if not ignore_file.is_symlink() and ignore_file.is_file():
            with ignore_file.open(encoding="utf-8") as stream:
                # Remove line endings without losing escaped trailing spaces.
                lines = (line.rstrip("\n") for line in stream)
                rules = (*rules, (parent, GitIgnoreSpec.from_lines(lines, backend="simple")))
        self.rules[parent] = rules
        ignored: set[str] = set()
        for name in names:
            path = parent / name
            is_directory = not path.is_symlink() and path.is_dir()
            excluded_directory = is_directory and (
                name.startswith(".") or name in {"__pycache__", "graphify-out"}
            )
            if excluded_directory or _matches_ignore(path, is_directory, rules):
                ignored.add(name)
        return ignored


def _matches_ignore(
    path: Path, is_directory: bool, rules: tuple[tuple[Path, GitIgnoreSpec], ...]
) -> bool:
    for base, spec in reversed(rules):
        relative = path.relative_to(base).as_posix() + ("/" if is_directory else "")
        match = spec.check_file(relative).include
        if match is not None:
            return match
    return False


@dataclass(frozen=True, slots=True)
class DependencyPreparation:
    """Image-layer selection, not a claim of fresh resolution in this campaign."""

    mode: Literal["locked", "resolved"]
    warning: str | None
    diagnostic_path: Path | None


def read_dependency_preparation(directory: Path) -> DependencyPreparation:
    """Require complete evidence rather than infer a mode from build logs."""
    value = cast(object, json.loads((directory / "dependencies.json").read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise ValueError("Dependency preparation evidence must be an object")
    payload = cast(dict[str, object], value)
    mode, warning, diagnostic = (payload.get(key) for key in ("mode", "warning", "diagnostic"))
    if set(payload) != {"mode", "warning", "diagnostic"}:
        raise ValueError("Dependency preparation evidence has invalid fields")
    if mode == "locked" and warning is None and diagnostic is None:
        return DependencyPreparation("locked", None, None)
    if mode != "resolved" or not isinstance(warning, str) or not warning.strip():
        raise ValueError("Dependency preparation evidence has invalid mode or warning")
    if diagnostic != "dependencies.log":
        raise ValueError("Dependency preparation evidence has invalid diagnostic")
    path = directory / "dependencies.log"
    if path.is_symlink() or not path.is_file() or not path.read_text(encoding="utf-8").strip():
        raise ValueError("Dependency preparation diagnostic is missing or empty")
    return DependencyPreparation("resolved", warning, path)
