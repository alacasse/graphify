"""Capture the candidate and the bounded sandbox payload for one image build."""

import shutil
from pathlib import Path

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
)


def prepare_context(subject: Path, directory: Path) -> Path:
    """Copy local changes once; callers must keep the candidate stable during capture."""
    context = directory / "context"
    context.mkdir()
    sandbox = Path(__file__).resolve().parent
    for filename in (*PAYLOAD, "Containerfile", "Containerfile.dockerignore"):
        shutil.copyfile(sandbox / filename, context / filename)
    shutil.copytree(
        subject,
        context / "subject",
        symlinks=True,
        ignore=_SourceFilter(),
    )
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
