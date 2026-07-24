"""Run Graphify installer lifecycle contracts inside isolated Docker roots."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.install_sandbox.docker import run_sandbox
from tools.install_sandbox.specs import SpecError, catalog_names, load_catalog


HARNESS_SPEC_DIR = Path(__file__).resolve().parent / "specs"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", required=True, type=Path)
    selection = result.add_mutually_exclusive_group(required=True)
    selection.add_argument("--target", choices=catalog_names(HARNESS_SPEC_DIR))
    selection.add_argument("--all", action="store_true", dest="all_targets")
    result.add_argument(
        "--scope",
        choices=("user", "project", "both"),
        default="both",
    )
    result.add_argument("--output", type=Path)
    return result


def default_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "out" / stamp


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = args.repo.expanduser().resolve()
    if not (repo / "pyproject.toml").is_file() or not (repo / "graphify").is_dir():
        print(f"error: not a Graphify source checkout: {repo}", file=sys.stderr)
        return 2
    try:
        load_catalog(HARNESS_SPEC_DIR)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output = (args.output or default_output()).expanduser().resolve()
    runtime = os.environ.get("GRAPHIFY_SANDBOX_RUNTIME", "docker")
    return run_sandbox(
        repo=repo,
        output=output,
        target=args.target,
        all_targets=args.all_targets,
        scope=args.scope,
        runtime=runtime,
    )


if __name__ == "__main__":
    raise SystemExit(main())
