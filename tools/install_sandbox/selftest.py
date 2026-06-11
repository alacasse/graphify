#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent.parent


def install_sandbox_modules() -> list[Path]:
    return sorted(path for path in HARNESS_DIR.glob("*.py") if path.name != "selftest.py")


def run_python_compile() -> None:
    subprocess.run([sys.executable, "-m", "py_compile", *(str(path) for path in install_sandbox_modules())], check=True)


def run_python_imports() -> None:
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    for path in install_sandbox_modules():
        importlib.import_module(f"tools.install_sandbox.{path.stem}")


def run_docker_smoke(repo: Path | None = None) -> None:
    if os.environ.get("GRAPHIFY_RUN_DOCKER_TESTS") != "1":
        raise RuntimeError("Docker smoke is gated; set GRAPHIFY_RUN_DOCKER_TESTS=1")
    repo = (repo or REPO_ROOT).resolve()
    output = HARNESS_DIR / "out" / "selftest-codex"
    command = [
        sys.executable,
        str(HARNESS_DIR / "run.py"),
        "--repo",
        str(repo),
        "--platform",
        "codex",
        "--scope",
        "project",
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight Graphify install sandbox self-checks.")
    parser.add_argument("--docker", action="store_true", help="Run gated Docker smoke test after compile checks.")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="Repository path for the optional Docker smoke test.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    run_python_compile()
    print("PASS run_python_compile")
    run_python_imports()
    print("PASS run_python_imports")
    if args.docker:
        run_docker_smoke(args.repo)
        print("PASS run_docker_smoke")
    print("selftest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
