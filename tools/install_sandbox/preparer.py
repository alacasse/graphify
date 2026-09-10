"""Capture the candidate and the bounded sandbox payload for one image build."""

import shutil
from pathlib import Path

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
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "graphify-out",
        ),
    )
    return context
