"""Prepare ordinary candidate dependencies inside the Docker build."""

import json
import signal
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from types import FrameType
from typing import cast


def prepare(metadata: Path, output: Path, python: str) -> None:
    """Let uv validate its lock offline, then let pip install exactly one selection.

    Docker's enclosing build budget bounds these commands. SIGTERM and SIGINT
    abort subprocess.run (which kills and waits for its child), never select fallback.
    """
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dependencies-") as temporary:
        requirements = Path(temporary) / "requirements.txt"
        warning = _export(metadata, requirements, output / "dependencies.log")
        if warning is not None:
            print(f"Warning: {warning}", file=sys.stderr, flush=True)
            # Failed later layers have no image to read; retain the refusal in build logs too.
            print((output / "dependencies.log").read_text(encoding="utf-8"), file=sys.stderr)
            requirements.write_text(_requirements(metadata), encoding="utf-8")
        subprocess.run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ],
            check=True,
        )
    (output / "dependencies.json").write_text(
        json.dumps(
            {
                "mode": "locked" if warning is None else "resolved",
                "warning": warning,
                "diagnostic": None if warning is None else "dependencies.log",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _export(metadata: Path, requirements: Path, diagnostic: Path) -> str | None:
    if not (metadata / "uv.lock").exists():
        warning = "Candidate uv.lock is absent; resolving dependencies from pyproject.toml."
        diagnostic.write_text(warning + "\n", encoding="utf-8")
        return warning
    with diagnostic.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--offline",
                "--no-python-downloads",
                "--no-default-groups",
                "--no-emit-project",
                "--python",
                sys.executable,
                "--no-header",
                "--no-annotate",
                "--output-file",
                str(requirements),
            ],
            cwd=metadata,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode:
            log.write(f"\nuv export exit code: {result.returncode}\n")
    if result.returncode < 0 or result.returncode in {130, 143}:
        result.check_returncode()
    if result.returncode:
        return "Candidate lock could not be validated offline; resolving from pyproject.toml."
    diagnostic.unlink()
    return None


def _requirements(metadata: Path) -> str:
    with (metadata / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream).get("project")
    if not isinstance(project, dict):
        raise ValueError("Candidate must declare static project.dependencies")
    fields = cast(dict[str, object], project)
    dynamic = fields.get("dynamic", [])
    if not isinstance(dynamic, list) or "dependencies" in dynamic:
        raise ValueError("Candidate must declare static project.dependencies")
    dependencies = fields.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("Candidate project.dependencies must be a list of requirement strings")
    items = cast(list[object], dependencies)
    if any(not _valid_requirement(item) for item in items):
        raise ValueError("Candidate project.dependencies contains an invalid requirement")
    return "\n".join(cast(list[str], items)) + "\n"


def _valid_requirement(item: object) -> bool:
    return (
        isinstance(item, str)
        and bool(item.strip())
        and "\n" not in item
        and "\r" not in item
        and not item.lstrip().startswith(("-", "#"))
    )


def _interrupt(_number: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _interrupt)
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
