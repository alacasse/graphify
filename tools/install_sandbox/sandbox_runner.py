#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import os
import platform as platform_mod
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import agent_summary
    from . import command_runner
    from . import file_effect_generated_artifacts
    from . import file_effect_oracle as file_effect_oracle_module
    from . import file_effect_state
    from . import reference_resolution
    from . import reports
    from . import scenario_file_effects_adapter
    from . import scenario_lifecycle_plan
    from . import scenario_lifecycle_support
    from . import source_snapshot
    from . import validation_plan
    from .harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
    from .status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values
    from .platform_specs import (
        DEFAULT_SCENARIO_REGISTRY,
        GRAPHIFY_MARKER,
        Scenario,
    )
except ImportError:
    import agent_summary
    import command_runner
    import file_effect_generated_artifacts  # type: ignore[no-redef]
    import file_effect_oracle as file_effect_oracle_module  # type: ignore[no-redef]
    import file_effect_state  # type: ignore[no-redef]
    import reference_resolution
    import reports
    import scenario_file_effects_adapter  # type: ignore[no-redef]
    import scenario_lifecycle_plan
    import scenario_lifecycle_support
    import source_snapshot
    import validation_plan
    from harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
    from status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values
    from platform_specs import (
        DEFAULT_SCENARIO_REGISTRY,
        GRAPHIFY_MARKER,
        Scenario,
    )


ROOT_REGISTRY = DEFAULT_SANDBOX_ROOT_REGISTRY
RUNTIME_ROOTS = ROOT_REGISTRY.runtime_paths()
HOME = RUNTIME_ROOTS["home"]
XDG_CONFIG_HOME = RUNTIME_ROOTS["xdg_config_home"]
PROJECT = RUNTIME_ROOTS["project"]
USER_CWD = RUNTIME_ROOTS["user_cwd"]
REPO_MOUNT = RUNTIME_ROOTS["repo_mount"]
SRC = RUNTIME_ROOTS["src"]
OUTPUT = RUNTIME_ROOTS["output"]

HARNESS_VERSION = "2026-06-01.1"
PACKAGE_NAME = "graphifyy"
INSTALL_MODE = "normal"
USER_SENTINEL = file_effect_state.USER_SENTINEL
STALE_GRAPHIFY_SENTINEL = file_effect_state.STALE_GRAPHIFY_SENTINEL
COPY_EXCLUDES = (
    *source_snapshot.COPY_EXCLUDES,
)
GENERATED_COPY_EXCLUDES = file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES
MANIFEST_PRUNE_DIRS = set(GENERATED_COPY_EXCLUDES) | {".mypy_cache", ".ruff_cache", "node_modules"}


ScenarioRunContext = scenario_lifecycle_support.ScenarioRunContext
StandardScenarioStages = scenario_lifecycle_support.StandardScenarioStages


ROOTS = ROOT_REGISTRY.scenario_roots(RUNTIME_ROOTS)

SCENARIO_REGISTRY = DEFAULT_SCENARIO_REGISTRY


@functools.lru_cache(maxsize=None)
def graphify_main_module():
    try:
        from graphify import __main__ as graphify_main
    except ModuleNotFoundError:
        for path in package_search_paths():
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
        from graphify import __main__ as graphify_main

    return graphify_main


@functools.lru_cache(maxsize=None)
def expected_graphify_version() -> str:
    return str(graphify_main_module().__version__)


@functools.lru_cache(maxsize=None)
def packaged_reference_resolution(platform_name: str) -> reference_resolution.PackagedReferenceResolution:
    graphify_main = graphify_main_module()
    spec = SCENARIO_REGISTRY.platform_spec(platform_name)
    return reference_resolution.resolve_packaged_references(
        platform_name,
        graphify_main=graphify_main,
        platform_spec=spec,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="In-container Graphify install scenario runner.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
    parser.add_argument("--copy-source", choices=("always", "auto"), default="always")
    parser.add_argument("--fail-fast-scenarios", action="store_true")
    return parser.parse_args(argv)


def read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
    return data


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_files(base: Path, *, scenario: Scenario | None = None, root_name: str | None = None) -> list[dict[str, object]]:
    if not base.exists():
        return []
    files: list[dict[str, object]] = []
    relevant_scenario = scenario if scenario is not None and root_name is not None else None
    relevant_root = root_name if relevant_scenario is not None else None
    oracle = file_effect_oracle()
    expected_relatives = oracle.expected_manifest_relatives(relevant_scenario, relevant_root) if relevant_scenario is not None and relevant_root is not None else None
    for path in oracle.pruned_file_walk(base):
        try:
            rel = path.relative_to(base).as_posix()
            stat = path.stat()
        except OSError:
            continue
        relative = Path(rel)
        if (
            expected_relatives is not None
            and relevant_scenario is not None
            and relevant_root is not None
            and relative not in expected_relatives
            and not oracle.is_relevant_generated_file(relevant_scenario, relevant_root, relative, path)
        ):
            continue
        files.append({"path": rel, "size": stat.st_size})
    return files


def write_file_manifest(path: Path, roots: dict[str, Path], *, scenario: Scenario | None = None, debug_full: bool = False) -> None:
    data = {name: list_files(root, scenario=None if debug_full else scenario, root_name=name) for name, root in roots.items()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_snapshot_config() -> source_snapshot.SourceSnapshotConfig:
    return source_snapshot.SourceSnapshotConfig(repo_mount=REPO_MOUNT, src=SRC, copy_excludes=COPY_EXCLUDES, manifest_prune_dirs=frozenset(MANIFEST_PRUNE_DIRS), package_name=PACKAGE_NAME, home=HOME)


def probe_read_only(path: Path) -> bool:
    probe = path / ".graphify-sandbox-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError:
        return True
    else:
        try:
            probe.unlink()
        except OSError:
            pass
        return False


def package_search_paths() -> list[Path]:
    return source_snapshot.package_search_paths(HOME)


def command_probe_summary(result: subprocess.CompletedProcess[str], command: tuple[str, ...]) -> dict[str, object]:
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": bool(getattr(result, "timed_out", False)),
    }


def version_from_probe(probe: dict[str, object]) -> str | None:
    stdout = probe.get("stdout")
    if not isinstance(stdout, str):
        return None
    match = re.search(r"\bgraphify\s+([^\s]+)", stdout)
    return match.group(1) if match else None


def install_graphify(env: dict[str, str]) -> dict[str, object]:
    artifact_dir = OUTPUT / "package-install"
    install_command = (sys.executable, "-m", "pip", "install", "--user", str(SRC))
    result = command_runner.run_capture(install_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir, command_class="package_install")
    if result.returncode != 0:
        raise RuntimeError("pip install failed; see package-install artifacts")

    metadata = source_snapshot.read_installed_package_metadata(PACKAGE_NAME, SRC, home=HOME)
    version_command = ("graphify", "--version")
    probe_result = command_runner.run_capture(version_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir / "graphify-version", command_class="graphify_version")
    if probe_result.returncode != 0:
        raise RuntimeError("graphify version probe failed; see package-install/graphify-version artifacts")
    probe = command_probe_summary(probe_result, version_command)
    metadata["version"] = metadata.get("version") or version_from_probe(probe)
    metadata["install_mode"] = INSTALL_MODE
    metadata["install_command"] = list(install_command)
    metadata["command_probe"] = probe
    if metadata.get("installed_from_copied_source") is not True:
        raise RuntimeError(
            "installed package provenance check failed; "
            f"package_name={metadata.get('package_name')}; "
            f"location={metadata.get('location')}; "
            f"direct_url={metadata.get('direct_url')}; "
            f"expected_source={SRC.resolve()}"
        )
    return metadata


def sandbox_env() -> dict[str, str]:
    env = os.environ.copy()
    current_roots = {
        "home": HOME,
        "xdg_config_home": XDG_CONFIG_HOME,
        "project": PROJECT,
        "repo_mount": REPO_MOUNT,
        "src": SRC,
        "output": OUTPUT,
    }
    for root in ROOT_REGISTRY.roots:
        if root.env_var is not None:
            env[root.env_var] = str(current_roots[root.name])
    env["PATH"] = f"{HOME / '.local' / 'bin'}:{env.get('PATH', '')}"
    return env


def reset_sandbox_dirs() -> None:
    for root in ROOT_REGISTRY.reset_roots():
        path = RUNTIME_ROOTS[root.name]
        path.mkdir(parents=True, exist_ok=True)
        for child in path.iterdir():
            if child.name in root.preserve_children:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    XDG_CONFIG_HOME.mkdir(parents=True, exist_ok=True)


def file_effect_oracle() -> file_effect_oracle_module.FileEffectOracle:
    return file_effect_oracle_module.FileEffectOracle(
        roots=ROOTS,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=expected_graphify_version,
        manifest_prune_dirs=MANIFEST_PRUNE_DIRS,
    )


def install_variant_artifact_label(label: str, used: set[str]) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label).strip(".-_").lower() or "variant"
    candidate = safe
    index = 2
    while candidate in used:
        candidate = f"{safe}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def run_install_variant(scenario: Scenario, command: tuple[str, ...], env: dict[str, str], artifact_dir: Path) -> dict[str, object]:
    oracle = file_effect_oracle()
    reset_sandbox_dirs()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    oracle.seed_user_owned_content(scenario)
    write_file_manifest(artifact_dir / "before-install-files.json", ROOTS, scenario=scenario)
    cwd = oracle.root_path(scenario.cwd_root)
    result = command_runner.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class="installer")
    checks = oracle.assert_expected_files(scenario) + oracle.assert_scope_boundaries(scenario) + oracle.assert_no_unexpected_graphify_files(scenario, phase="install")
    state = oracle.scenario_file_state(scenario)
    write_file_manifest(artifact_dir / "after-install-files.json", ROOTS, scenario=scenario)
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "checks": checks,
        "state": state,
        "passed": result.returncode == 0 and all(check["ok"] for check in checks),
    }


def run_equivalence_check(scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]:
    variants = SCENARIO_REGISTRY.equivalent_install_variants(scenario)
    equivalence_dir = artifact_dir / "generic-direct-equivalence"
    if variants is None:
        (equivalence_dir / "status.json").parent.mkdir(parents=True, exist_ok=True)
        (equivalence_dir / "status.json").write_text(json.dumps(SCENARIO_REGISTRY.equivalence_status(scenario), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return []

    primary_variant, alternate_variant = variants
    used_labels: set[str] = set()
    primary_label = install_variant_artifact_label(primary_variant.label, used_labels)
    alternate_label = install_variant_artifact_label(alternate_variant.label, used_labels)
    primary = run_install_variant(scenario, primary_variant.command, env, equivalence_dir / primary_label)
    alternate_result = run_install_variant(scenario, alternate_variant.command, env, equivalence_dir / alternate_label)
    same_effects = primary["state"] == alternate_result["state"]
    passed = bool(primary["passed"] and alternate_result["passed"] and same_effects)
    report = {
        "status": "runnable",
        "passed": passed,
        "primary_label": primary_variant.label,
        "alternate_label": alternate_variant.label,
        "primary": primary,
        "alternate": alternate_result,
        "same_file_effects": same_effects,
    }
    (equivalence_dir / "equivalence.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [
        {
            "path": f"{scenario.platform}/{scenario.scope}",
            "ok": passed,
            "detail": f"generic_direct_equivalent={same_effects}; primary_exit={primary['exit_code']}; alternate_exit={alternate_result['exit_code']}",
        }
    ]


def risk_report(scenario: Scenario, passed: bool) -> dict[str, object]:
    statuses = [RISK_GRAPHIFY_VERIFIED if passed else RISK_GRAPHIFY_FAILED]
    return {
        "statuses": statuses,
        "notes": list(scenario.risk_notes),
        "known_status_values": known_status_values(),
    }


def scenario_lifecycle_hooks(
    *,
    run_scenario_func=None,
    run_universal_uninstall_scenario_func=None,
    run_purge_scenario_func=None,
) -> scenario_lifecycle_support.ScenarioLifecycleHooks:
    oracle = file_effect_oracle()
    return scenario_lifecycle_support.ScenarioLifecycleHooks(
        paths=scenario_lifecycle_support.SandboxPaths(
            output=OUTPUT,
            roots=ROOTS,
            project=PROJECT,
            user_cwd=USER_CWD,
            utc_timestamp=utc_timestamp,
            root_path=oracle.root_path,
            reset_sandbox_dirs=reset_sandbox_dirs,
        ),
        file_effects=scenario_file_effects_adapter.ScenarioFileEffectsAdapter(
            oracle=oracle,
            write_file_manifest=write_file_manifest,
            run_equivalence_check=run_equivalence_check,
        ),
        commands=scenario_lifecycle_support.CommandExecutor(command_runner.run_capture),
        artifacts=scenario_lifecycle_support.ScenarioArtifacts(
            risk_report=risk_report,
            command_artifact_summary=lambda artifact_dir: reports.command_artifact_summary(artifact_dir, output_root=OUTPUT),
            combined_status=combined_status,
            known_status_values=known_status_values,
        ),
        scenario_registry=SCENARIO_REGISTRY,
        matrix_overrides=scenario_lifecycle_support.MatrixRunnerOverrides(
            run_scenario=run_scenario_func,
            run_universal_uninstall_scenario=run_universal_uninstall_scenario_func,
            run_purge_scenario=run_purge_scenario_func,
        ),
    )


def preflight() -> dict[str, object]:
    SCENARIO_REGISTRY.validate_roots(ROOT_REGISTRY.declared_expected_root_names())
    validation_plan.DEFAULT_HARNESS_POLICY.validate_roots(ROOT_REGISTRY.declared_expected_root_names())
    for root in ROOT_REGISTRY.roots:
        path = RUNTIME_ROOTS[root.name]
        if root.reset or root.mount_mode == "rw" or root.name == "xdg_config_home":
            path.mkdir(parents=True, exist_ok=True)
    checks: dict[str, object] = {root.name: str(RUNTIME_ROOTS[root.name]) for root in ROOT_REGISTRY.roots}
    required_keys: list[str] = []
    for root in ROOT_REGISTRY.preflight_roots():
        path = RUNTIME_ROOTS[root.name]
        if root.sandbox_path_required is not None:
            key = "xdg_is_sandbox" if root.name == "xdg_config_home" else f"{root.name}_is_sandbox"
            checks[key] = str(path) == root.sandbox_path_required
            required_keys.append(key)
        if root.mount_mode == "ro":
            exists_key = f"{root.name}_exists"
            read_only_key = f"{root.name}_read_only"
            checks[exists_key] = path.is_dir()
            checks[read_only_key] = probe_read_only(path) if path.exists() else False
            required_keys.extend([exists_key, read_only_key])
    (OUTPUT / "preflight.json").write_text(json.dumps(checks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all(bool(checks[key]) for key in required_keys):
        raise RuntimeError(f"sandbox invariant failed: {checks}")
    return checks


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = sandbox_env()
    preflight_data = preflight()
    src_data = source_snapshot.copy_source_tree(args.copy_source, config=source_snapshot_config())
    package_data = install_graphify(env)
    hooks = scenario_lifecycle_hooks()
    plan = validation_plan.build_validation_plan(
        SCENARIO_REGISTRY,
        all_platforms=args.all,
        platform_name=args.platform,
        scope=args.scope,
    )

    results = scenario_lifecycle_plan.run_validation_plan(plan, env, hooks, fail_fast_scenarios=args.fail_fast_scenarios)
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed

    coverage = list(plan.coverage_records)
    platform_coverage_summary = dict(plan.platform_coverage_summary)
    platform_coverage_summary["universal_scenario_count"] = max(0, len(results) - len(plan.standard_scenarios))
    manifest = {
        "harness_version": HARNESS_VERSION,
        "python_version": sys.version,
        "os_release": read_os_release(),
        "architecture": platform_mod.machine(),
        "graphify_version": package_data.get("version"),
        "package_install": package_data,
        "source_snapshot": src_data,
        "preflight": preflight_data,
        "target_runtime_verification": plan.target_runtime_verification,
        "target_runtime_validation_sections": list(plan.target_runtime_validation_sections),
        "platform_coverage": coverage,
        "platform_coverage_summary": platform_coverage_summary,
        "scenario_count": len(results),
        "graphify_file_effect_pass_count": passed,
        "graphify_file_effect_fail_count": failed,
        "pass_count": passed,
        "fail_count": failed,
        "results": results,
        "risk_status_values": known_status_values(),
    }
    reports.write_manifest_json(OUTPUT / "manifest.json", manifest)
    reports.write_report_md(OUTPUT / "report.md", manifest)
    agent_summary.write_summary(OUTPUT, agent_summary.summarize_output(OUTPUT))
    reports.print_summary(OUTPUT, passed=passed, failed=failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
