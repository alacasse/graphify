#!/usr/bin/env python3
"""Canonical development quality gate for the install sandbox."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    CheckResult,
    CheckStatus,
    FastCheckConfigurationError,
    run_fast_checks,
)
from install_sandbox_quality_docker import (
    DockerConfigurationError,
    DockerFailed,
    DockerPassed,
    DockerTimedOut,
    run_docker_gate,
)
from install_sandbox_quality_evidence import (
    DockerSelection,
    FullDockerSelection,
    TargetedDockerSelection,
)


def _target(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("Docker target must not be empty")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("fast", help="run the inexpensive install-sandbox checks")
    docker = subcommands.add_parser("docker", help="run the official Docker diagnostic")
    selection = docker.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--target",
        type=_target,
        help="run one catalog-derived Install Target",
    )
    selection.add_argument("--all", action="store_true", dest="all_targets")
    return parser


def _report(result: CheckResult) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    suffix = "" if result.exit_code is None else f" (exit {result.exit_code})"
    print(f"[{result.status.value}] {result.name}{suffix}")


def _fast(repository: Path) -> int:
    run = run_fast_checks(repository)
    if isinstance(run, FastCheckConfigurationError):
        print(f"fast: CONFIGURATION ERROR: {run.message}", file=sys.stderr)
        return CONFIGURATION_EXIT

    for result in run.results:
        _report(result)

    if any(result.configuration_error for result in run.results):
        print("fast: CONFIGURATION ERROR")
        return CONFIGURATION_EXIT
    if any(result.status is CheckStatus.FAIL for result in run.results):
        print("fast: FAIL")
        return 1
    print("fast: PASS")
    return 0


def _docker(repository: Path, selection: DockerSelection) -> int:
    run = run_docker_gate(repository, selection)
    print(f"diagnostic bundle: {run.context.bundle}")
    for result in run.context.results:
        _report(result)

    if isinstance(run, DockerConfigurationError):
        print("docker: CONFIGURATION ERROR")
        return CONFIGURATION_EXIT
    if isinstance(run, DockerTimedOut):
        print("docker: TIMEOUT")
        return 124
    if isinstance(run, DockerFailed):
        print(run.reason, file=sys.stderr)
        print("docker: FAIL")
        return 1
    if not isinstance(run, DockerPassed):
        raise AssertionError(f"unhandled Docker gate result: {type(run).__name__}")
    if run.advisory_findings:
        print(
            f"docker: advisory legacy Product Findings={len(run.advisory_findings)}",
            file=sys.stderr,
        )
    print("docker: PASS")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "fast":
        return _fast(Path.cwd().resolve())
    if arguments.command == "docker":
        selection: DockerSelection
        if arguments.all_targets:
            selection = FullDockerSelection()
        else:
            if not isinstance(arguments.target, str):
                raise AssertionError("targeted Docker selection is missing its target")
            selection = TargetedDockerSelection(arguments.target)
        return _docker(
            Path.cwd().resolve(),
            selection,
        )
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
