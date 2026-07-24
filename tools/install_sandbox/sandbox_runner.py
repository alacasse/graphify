"""Thin in-container entrypoint for lifecycle execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .lifecycle import copy_and_install_package, run_purge_check, run_scenario
from .models import SandboxRoots, Scenario, ScenarioResult, Scope
from .reporting import build_manifest, write_run_outputs
from .specs import EXPECTED_TARGETS, SpecError, load_catalog


HARNESS_SPEC_DIR = Path(__file__).resolve().parent / "specs"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    selection = result.add_mutually_exclusive_group(required=True)
    selection.add_argument("--target", choices=EXPECTED_TARGETS)
    selection.add_argument("--all", action="store_true", dest="all_targets")
    result.add_argument(
        "--scope",
        choices=("user", "project", "both"),
        default="both",
    )
    return result


def roots_from_environment() -> SandboxRoots:
    required = {
        "home": "HOME",
        "xdg": "XDG_CONFIG_HOME",
        "project": "GRAPHIFY_SANDBOX_PROJECT",
        "user_cwd": "GRAPHIFY_SANDBOX_USER_CWD",
        "source": "GRAPHIFY_SANDBOX_SOURCE",
        "repo_mount": "GRAPHIFY_SANDBOX_REPO",
        "output": "GRAPHIFY_SANDBOX_OUTPUT",
    }
    values: dict[str, Path] = {}
    for name, variable in required.items():
        raw = os.environ.get(variable)
        if not raw:
            raise RuntimeError(f"missing required container environment: {variable}")
        values[name] = Path(raw)
    resolved = [path.resolve() for path in values.values()]
    if len(set(resolved)) != len(resolved):
        raise RuntimeError("sandbox roots must all be distinct")
    return SandboxRoots(**values)


def _unsupported(target, scope: Scope, output: Path) -> ScenarioResult:
    reason = target.unsupported[scope]
    return ScenarioResult(
        scenario=f"{target.name}-{scope.value}",
        target=target.name,
        scope=scope.value,
        status="UNSUPPORTED",
        phases=[],
        limitations=(reason, *target.limitations),
        artifact_dir=None,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    roots = roots_from_environment()
    try:
        catalog = load_catalog(HARNESS_SPEC_DIR)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    package = copy_and_install_package(roots)
    if package["repo_mount_read_only"] is not True:
        raise RuntimeError("repository mount is writable; refusing unsafe sandbox run")

    names = list(EXPECTED_TARGETS) if args.all_targets else [args.target]
    scopes = (
        list(Scope)
        if args.scope == "both"
        else [Scope(args.scope)]
    )
    results: list[ScenarioResult] = []
    for name in names:
        target = catalog[name]
        for scope in scopes:
            if not target.supports(scope):
                results.append(_unsupported(target, scope, roots.output))
                continue
            print(f"==> {name} / {scope.value}", flush=True)
            try:
                results.append(
                    run_scenario(Scenario(target=target, scope=scope), roots)
                )
            except Exception as exc:
                print(f"scenario {name}-{scope.value} crashed: {exc}", file=sys.stderr)
                results.append(
                    ScenarioResult(
                        scenario=f"{name}-{scope.value}",
                        target=name,
                        scope=scope.value,
                        status="FAIL",
                        phases=[],
                        limitations=target.limitations,
                        artifact_dir=f"scenarios/{name}-{scope.value}",
                    )
                )
    purge = run_purge_check(roots)
    manifest = build_manifest(
        repo=roots.repo_mount,
        selection={
            "target": args.target,
            "all": args.all_targets,
            "scope": args.scope,
        },
        package=package,
        results=results,
        purge=purge,
    )
    write_run_outputs(roots.output, manifest)
    failed = any(result.status == "FAIL" for result in results)
    return 1 if failed or purge["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
