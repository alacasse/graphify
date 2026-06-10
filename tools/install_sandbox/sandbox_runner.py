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
from typing import Iterable

try:
    from . import command_runner
    from . import file_effects
    from . import reports
    from . import scenario_lifecycle
    from . import source_snapshot
    from .platform_specs import (
        ALL_PLATFORMS,
        DEFAULT_SCENARIO_REGISTRY,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SIMULATED_LINUX_LAYOUT_NOTE,
        ExpectedPath,
        PlatformSpec,
        Scenario,
        ScenarioRegistry,
        ScopeSpec,
    )
except ImportError:
    import command_runner
    import file_effects
    import reports
    import scenario_lifecycle
    import source_snapshot
    from platform_specs import (
        ALL_PLATFORMS,
        DEFAULT_SCENARIO_REGISTRY,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SIMULATED_LINUX_LAYOUT_NOTE,
        ExpectedPath,
        PlatformSpec,
        Scenario,
        ScenarioRegistry,
        ScopeSpec,
    )


HOME = Path(os.environ.get("HOME", "/tmp/graphify-home"))
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
PROJECT = Path(os.environ.get("GRAPHIFY_PROJECT", "/tmp/graphify-project"))
USER_CWD = Path("/tmp/graphify-user-cwd")
REPO_MOUNT = Path(os.environ.get("GRAPHIFY_REPO_MOUNT", "/mnt/graphify-repo"))
SRC = Path(os.environ.get("GRAPHIFY_SRC", "/tmp/graphify-src"))
OUTPUT = Path(os.environ.get("GRAPHIFY_OUTPUT", "/sandbox-out"))

HARNESS_VERSION = "2026-06-01.1"
PACKAGE_NAME = "graphifyy"
INSTALL_MODE = "normal"
USER_SENTINEL = file_effects.USER_SENTINEL
STALE_GRAPHIFY_SENTINEL = file_effects.STALE_GRAPHIFY_SENTINEL
GRAPHIFY_MARKER = file_effects.GRAPHIFY_MARKER
RISK_GRAPHIFY_VERIFIED = "graphify_install_verified"
RISK_GRAPHIFY_FAILED = "graphify_install_failed"
COMMAND_TIMEOUTS = command_runner.COMMAND_TIMEOUTS
USER_CONTENT_PRESERVING_RELATIVES = file_effects.USER_CONTENT_PRESERVING_RELATIVES

WINDOWS_VALIDATION_TARGETS = (
    *reports.WINDOWS_VALIDATION_TARGETS,
)
COPY_EXCLUDES = (
    *source_snapshot.COPY_EXCLUDES,
)
GENERATED_COPY_EXCLUDES = file_effects.GENERATED_COPY_EXCLUDES
MANIFEST_PRUNE_DIRS = set(GENERATED_COPY_EXCLUDES) | {".mypy_cache", ".ruff_cache", "node_modules"}


ScenarioRunContext = scenario_lifecycle.ScenarioRunContext
StandardScenarioStages = scenario_lifecycle.StandardScenarioStages


ROOTS = {
    "home": HOME,
    "project": PROJECT,
    "user_cwd": USER_CWD,
}

SCENARIO_REGISTRY = DEFAULT_SCENARIO_REGISTRY


scenario_id = scenario_lifecycle.scenario_id


def sandbox_platform_specs() -> dict[str, PlatformSpec]:
    return SCENARIO_REGISTRY.specs


def platform_spec(platform_name: str) -> PlatformSpec:
    return SCENARIO_REGISTRY.platform_spec(platform_name)


def user_skill(platform_name: str) -> ExpectedPath:
    return SCENARIO_REGISTRY.user_skill(platform_name)


def project_skill(platform_name: str) -> ExpectedPath:
    return SCENARIO_REGISTRY.project_skill(platform_name)


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return SCENARIO_REGISTRY.unsupported_scope_reason(platform_name, scope)


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    return SCENARIO_REGISTRY.direct_uninstall_command(platform_name)


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return SCENARIO_REGISTRY.generic_install_command(platform_name, scope)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    return SCENARIO_REGISTRY.direct_install_command(platform_name, scope)


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    return SCENARIO_REGISTRY.equivalent_install_command(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return SCENARIO_REGISTRY.equivalence_status(scenario)


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    return SCENARIO_REGISTRY.platform_scenarios(platform_name, scope)


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    return SCENARIO_REGISTRY.make_scenario(platform_name, scope)


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    return SCENARIO_REGISTRY.risk_notes(*notes, platform_name=platform_name)




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


def packaged_references_dir(platform_name: str) -> Path | None:
    graphify_main = graphify_main_module()
    spec = platform_spec(platform_name)
    if spec.reference_bundles:
        package_dir = Path(graphify_main.__file__).parent
        for bundle in spec.reference_bundles:
            if bundle == "vscode" and not (package_dir / "skill-vscode.md").exists():
                continue
            bundle_dir = package_dir / "skills" / bundle
            if bundle_dir.is_dir():
                return bundle_dir / "references"
        return None
    if spec.uses_packaged_references:
        return graphify_main._packaged_skill_refs_dir(spec.name)
    return None


@functools.lru_cache(maxsize=None)
def packaged_reference_names(platform_name: str) -> list[str] | None:
    refs_dir = packaged_references_dir(platform_name)
    if refs_dir is None:
        return None
    if not refs_dir.is_dir():
        return []
    return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())


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


def run_capture(
    command: Iterable[str],
    *,
    cwd: Path,
    env: dict[str, str],
    artifact_dir: Path | None = None,
    command_class: str = "installer",
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return command_runner.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class=command_class, timeout_seconds=timeout_seconds)


timeout_for = command_runner.timeout_for
timeout_text = command_runner.timeout_text
command_display = command_runner.command_display
write_command_start_artifacts = command_runner.write_command_start_artifacts
execute_command = command_runner.execute_command
command_result_metadata = command_runner.command_result_metadata
write_command_result_artifacts = command_runner.write_command_result_artifacts
attach_command_metadata = command_runner.attach_command_metadata


def list_files(base: Path, *, scenario: Scenario | None = None, root_name: str | None = None) -> list[dict[str, object]]:
    if not base.exists():
        return []
    files: list[dict[str, object]] = []
    relevant_scenario = scenario if scenario is not None and root_name is not None else None
    relevant_root = root_name if relevant_scenario is not None else None
    expected_relatives = expected_manifest_relatives(relevant_scenario, relevant_root) if relevant_scenario is not None and relevant_root is not None else None
    for path in pruned_file_walk(base):
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
            and not is_relevant_generated_file(relevant_scenario, relevant_root, relative, path)
        ):
            continue
        files.append({"path": rel, "size": stat.st_size})
    return files


def write_file_manifest(path: Path, roots: dict[str, Path], *, scenario: Scenario | None = None, debug_full: bool = False) -> None:
    data = {name: list_files(root, scenario=None if debug_full else scenario, root_name=name) for name, root in roots.items()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_snapshot_config() -> source_snapshot.SourceSnapshotConfig:
    return source_snapshot.SourceSnapshotConfig(repo_mount=REPO_MOUNT, src=SRC, copy_excludes=COPY_EXCLUDES, manifest_prune_dirs=frozenset(MANIFEST_PRUNE_DIRS), package_name=PACKAGE_NAME, home=HOME)


sha256 = source_snapshot.sha256


def should_exclude_source_path(relative: str) -> bool:
    return source_snapshot.should_exclude_source_path(relative, COPY_EXCLUDES)


def copy_source_ignore(directory: str, names: list[str]) -> set[str]:
    return source_snapshot.copy_source_ignore(directory, names, source_snapshot_config())


def repo_relative(path: Path) -> str:
    return source_snapshot.repo_relative(path, source_snapshot_config())


def validate_source_symlink(src_path: Path) -> str:
    return source_snapshot.validate_source_symlink(src_path, source_snapshot_config())


def validate_source_symlinks_for_copytree() -> None:
    source_snapshot.validate_source_symlinks_for_copytree(source_snapshot_config())


def source_manifest(src: Path) -> dict[str, object]:
    return source_snapshot.source_manifest(src, source_snapshot_config())


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


def copy_tracked_source_tree() -> dict[str, object] | None:
    return source_snapshot.copy_tracked_source_tree(source_snapshot_config())


def copy_source_tree(copy_source: str = "always") -> dict[str, object]:
    return source_snapshot.copy_source_tree(copy_source, config=source_snapshot_config())


def package_search_paths() -> list[Path]:
    return source_snapshot.package_search_paths(HOME)


def direct_url_source_path(direct_url: dict[str, object] | None) -> Path | None:
    return source_snapshot.direct_url_source_path(direct_url)


package_metadata_value = source_snapshot.package_metadata_value


def dist_to_metadata(dist, source: Path) -> dict[str, object]:
    return source_snapshot.dist_to_metadata(dist, source, PACKAGE_NAME)


def metadata_from_dist_info(dist_info: Path, source: Path) -> dict[str, object] | None:
    return source_snapshot.metadata_from_dist_info(dist_info, source, PACKAGE_NAME)


def read_installed_package_metadata(package_name: str, source: Path, search_paths: list[Path] | None = None) -> dict[str, object]:
    return source_snapshot.read_installed_package_metadata(package_name, source, search_paths, home=HOME)


def command_probe_summary(result: subprocess.CompletedProcess[str], command: tuple[str, ...]) -> dict[str, object]:
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": bool(getattr(result, "timed_out", False)),
    }


def known_status_values() -> list[str]:
    return [RISK_GRAPHIFY_VERIFIED, RISK_GRAPHIFY_FAILED]


def combined_status(graphify_passed: bool) -> str:
    return RISK_GRAPHIFY_VERIFIED if graphify_passed else RISK_GRAPHIFY_FAILED


def artifact_relpath(path: Path, root: Path = OUTPUT) -> str:
    return reports.artifact_relpath(path, root)


def read_json_object(path: Path) -> dict[str, object]:
    return reports.read_json_object(path)


def text_snippet(path: Path, limit: int = 500) -> str:
    return reports.text_snippet(path, limit)


def command_artifact_summary(artifact_dir: Path) -> dict[str, object]:
    return reports.command_artifact_summary(artifact_dir, output_root=OUTPUT)


def status_label(result: dict[str, object]) -> str:
    return reports.status_label(result)


def md_cell(value: object) -> str:
    return reports.md_cell(value)


def md_code(value: object) -> str:
    return reports.md_code(value)


def md_row(cells: Iterable[object]) -> str:
    return reports.md_row(cells)


def md_separator(column_count: int, *, right_align: Iterable[int] = ()) -> str:
    return reports.md_separator(column_count, right_align=right_align)


def md_table(headers: Iterable[str], rows: Iterable[Iterable[object]], *, right_align: Iterable[int] = ()) -> list[str]:
    return reports.md_table(headers, rows, right_align=right_align)


def object_dict(value: object) -> dict[str, object]:
    return reports.object_dict(value)


def object_list(value: object) -> list[object]:
    return reports.object_list(value)


def object_dicts(value: object) -> list[dict[str, object]]:
    return reports.object_dicts(value)


def check_record(path: Path | str, ok: bool, detail: str, *, root: str | None = None, relative: str | Path | None = None, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


def render_report_md(manifest: dict[str, object]) -> str:
    return reports.render_report_md(manifest)


def write_report_md(path: Path, manifest: dict[str, object]) -> None:
    reports.write_report_md(path, manifest)


def write_manifest_json(path: Path, manifest: dict[str, object]) -> None:
    reports.write_manifest_json(path, manifest)


def default_windows_validation_status() -> dict[str, object]:
    return reports.default_windows_validation_status()


def version_from_probe(probe: dict[str, object]) -> str | None:
    stdout = probe.get("stdout")
    if not isinstance(stdout, str):
        return None
    match = re.search(r"\bgraphify\s+([^\s]+)", stdout)
    return match.group(1) if match else None


def install_graphify(env: dict[str, str]) -> dict[str, object]:
    artifact_dir = OUTPUT / "package-install"
    install_command = (sys.executable, "-m", "pip", "install", "--user", str(SRC))
    result = run_capture(install_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir, command_class="package_install")
    if result.returncode != 0:
        raise RuntimeError("pip install failed; see package-install artifacts")

    metadata = read_installed_package_metadata(PACKAGE_NAME, SRC)
    version_command = ("graphify", "--version")
    probe_result = run_capture(version_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir / "graphify-version", command_class="graphify_version")
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
    env["HOME"] = str(HOME)
    env["XDG_CONFIG_HOME"] = str(XDG_CONFIG_HOME)
    env["GRAPHIFY_PROJECT"] = str(PROJECT)
    env["PATH"] = f"{HOME / '.local' / 'bin'}:{env.get('PATH', '')}"
    return env


def reset_sandbox_dirs() -> None:
    for path in (HOME, PROJECT, USER_CWD):
        path.mkdir(parents=True, exist_ok=True)
        for child in path.iterdir():
            if path == HOME and child.name == ".local":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    XDG_CONFIG_HOME.mkdir(parents=True, exist_ok=True)


def file_effect_oracle() -> file_effects.FileEffectOracle:
    return file_effects.FileEffectOracle(
        roots=ROOTS,
        packaged_reference_names=packaged_reference_names,
        expected_graphify_version=expected_graphify_version,
        manifest_prune_dirs=MANIFEST_PRUNE_DIRS,
    )


# Compatibility forwarding names for existing selftests and monkeypatches.
check_record = file_effects.check_record
expected_kind_status = file_effects.expected_kind_status
json_value_contains_marker = file_effects.json_value_contains_marker
graphify_command_hook_present = file_effects.graphify_command_hook_present
hooks_by_event = file_effects.hooks_by_event
claude_like_settings_status = file_effects.claude_like_settings_status
codex_hooks_status = file_effects.codex_hooks_status
gemini_settings_status = file_effects.gemini_settings_status
plugin_config_status = file_effects.plugin_config_status
platform_json_status = file_effects.platform_json_status
assert_idempotent_state = file_effects.assert_idempotent_state


def root_path(root: str) -> Path:
    return file_effect_oracle().root_path(root)


def expected_path(entry: ExpectedPath) -> Path:
    return file_effect_oracle().expected_path(entry)


def is_skill_expected(entry: ExpectedPath) -> bool:
    return file_effect_oracle().is_skill_expected(entry)


def skill_dir_for_entry(entry: ExpectedPath) -> Path:
    return file_effect_oracle().skill_dir_for_entry(entry)


def skill_relative_dir(entry: ExpectedPath) -> Path:
    return file_effect_oracle().skill_relative_dir(entry)


def skill_assertion_record(entry: ExpectedPath, relative: Path, ok: bool, detail: str) -> dict[str, object]:
    return file_effect_oracle().skill_assertion_record(entry, relative, ok, detail)


def installed_reference_names(refs_dir: Path) -> list[str]:
    return file_effect_oracle().installed_reference_names(refs_dir)


def skill_reference_pointers(skill_text: str) -> list[str]:
    return file_effect_oracle().skill_reference_pointers(skill_text)


def check_skill_version(entry: ExpectedPath) -> dict[str, object]:
    return file_effect_oracle().check_skill_version(entry)


def check_references_tmp_absent(entry: ExpectedPath) -> dict[str, object]:
    return file_effect_oracle().check_references_tmp_absent(entry)


def check_packaged_references(scenario: Scenario, entry: ExpectedPath) -> dict[str, object]:
    return file_effect_oracle().check_packaged_references(scenario, entry)


def check_skill_reference_pointers(entry: ExpectedPath, skill_text: str) -> dict[str, object]:
    return file_effect_oracle().check_skill_reference_pointers(entry, skill_text)


def assert_installed_skill_sidecar(scenario: Scenario, entry: ExpectedPath) -> list[dict[str, object]]:
    return file_effect_oracle().assert_installed_skill_sidecar(scenario, entry)


def assert_installed_skill_sidecars(scenario: Scenario) -> list[dict[str, object]]:
    return file_effect_oracle().assert_installed_skill_sidecars(scenario)


def progressive_skill_entries(scenario: Scenario) -> list[ExpectedPath]:
    return file_effect_oracle().progressive_skill_entries(scenario)


def seed_stale_skill_sidecars(scenario: Scenario) -> list[dict[str, object]]:
    return file_effect_oracle().seed_stale_skill_sidecars(scenario)


def expected_manifest_relatives(scenario: Scenario, root_name: str) -> set[Path]:
    return file_effect_oracle().expected_manifest_relatives(scenario, root_name)


def pruned_file_walk(base: Path) -> Iterable[Path]:
    return file_effect_oracle().pruned_file_walk(base)


def should_seed_user_content(entry: ExpectedPath) -> bool:
    return file_effect_oracle().should_seed_user_content(entry)


def should_seed_stale_graphify_section(entry: ExpectedPath) -> bool:
    return file_effect_oracle().should_seed_stale_graphify_section(entry)


def seeded_text(entry: ExpectedPath) -> str:
    return file_effect_oracle().seeded_text(entry)


def seed_user_owned_content(scenario: Scenario) -> None:
    file_effect_oracle().seed_user_owned_content(scenario)


def json_marker_status(path: Path, entry: ExpectedPath) -> tuple[bool, str]:
    return file_effect_oracle().json_marker_status(path, entry)


def text_marker_status(path: Path, entry: ExpectedPath) -> tuple[bool, str]:
    return file_effect_oracle().text_marker_status(path, entry)


def expected_entry_status(entry: ExpectedPath) -> tuple[bool, str]:
    return file_effect_oracle().expected_entry_status(entry)


def assert_expected_files(scenario: Scenario) -> list[dict[str, object]]:
    return file_effect_oracle().assert_expected_files(scenario)


def uninstalled_entry_status(entry: ExpectedPath) -> tuple[bool, str]:
    return file_effect_oracle().uninstalled_entry_status(entry)


def uninstalled_skill_sidecar_checks(entry: ExpectedPath) -> list[dict[str, object]]:
    return file_effect_oracle().uninstalled_skill_sidecar_checks(entry)


def assert_uninstalled(scenario: Scenario) -> list[dict[str, object]]:
    return file_effect_oracle().assert_uninstalled(scenario)


def expected_generated_relative_keys(scenario: Scenario) -> set[tuple[str, str]]:
    return file_effect_oracle().expected_generated_relative_keys(scenario)


def assert_no_unexpected_graphify_files(
    scenario: Scenario,
    *,
    phase: str,
    expected_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    return file_effect_oracle().assert_no_unexpected_graphify_files(scenario, phase=phase, expected_keys=expected_keys)


def assert_scope_boundaries(scenario: Scenario) -> list[dict[str, object]]:
    return file_effect_oracle().assert_scope_boundaries(scenario)


def file_fingerprint(path: Path, marker: str | None = None) -> dict[str, object]:
    return file_effect_oracle().file_fingerprint(path, marker)


def scenario_file_state(scenario: Scenario) -> dict[str, dict[str, object]]:
    return file_effect_oracle().scenario_file_state(scenario)


def should_exclude_generated_path(relative: Path) -> bool:
    return file_effect_oracle().should_exclude_generated_path(relative)


def is_expected_generated_key(scenario: Scenario, root_name: str, relative: Path) -> bool:
    return file_effect_oracle().is_expected_generated_key(scenario, root_name, relative)


def is_skill_sidecar_relative(scenario: Scenario, root_name: str, relative: Path) -> bool:
    return file_effect_oracle().is_skill_sidecar_relative(scenario, root_name, relative)


def is_adjacent_graphify_version(scenario: Scenario, root_name: str, relative: Path) -> bool:
    return file_effect_oracle().is_adjacent_graphify_version(scenario, root_name, relative)


def is_small_text_candidate(path: Path) -> bool:
    return file_effect_oracle().is_small_text_candidate(path)


def file_mentions_graphify_or_sentinel(path: Path) -> bool:
    return file_effect_oracle().file_mentions_graphify_or_sentinel(path)


def is_relevant_generated_file(scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
    return file_effect_oracle().is_relevant_generated_file(scenario, root_name, relative, path)


def copy_generated_files(scenario: Scenario, artifact_dir: Path) -> None:
    file_effect_oracle().copy_generated_files(scenario, artifact_dir)


def command_style(command: tuple[str, ...], platform_name: str) -> str:
    if len(command) >= 2 and command[1] == "install":
        return "generic"
    if len(command) >= 3 and command[1] == platform_name and command[2] == "install":
        return "direct"
    return "command"


def run_install_variant(scenario: Scenario, command: tuple[str, ...], env: dict[str, str], artifact_dir: Path) -> dict[str, object]:
    reset_sandbox_dirs()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    seed_user_owned_content(scenario)
    write_file_manifest(artifact_dir / "before-install-files.json", ROOTS, scenario=scenario)
    cwd = root_path(scenario.cwd_root)
    result = run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class="installer")
    checks = assert_expected_files(scenario) + assert_scope_boundaries(scenario) + assert_no_unexpected_graphify_files(scenario, phase="install")
    state = scenario_file_state(scenario)
    write_file_manifest(artifact_dir / "after-install-files.json", ROOTS, scenario=scenario)
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "checks": checks,
        "state": state,
        "passed": result.returncode == 0 and all(check["ok"] for check in checks),
    }


def run_equivalence_check(scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]:
    alternate = equivalent_install_command(scenario)
    equivalence_dir = artifact_dir / "generic-direct-equivalence"
    if alternate is None:
        (equivalence_dir / "status.json").parent.mkdir(parents=True, exist_ok=True)
        (equivalence_dir / "status.json").write_text(json.dumps(equivalence_status(scenario), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return []

    primary_style = command_style(scenario.install_command, scenario.platform)
    alternate_style = command_style(alternate, scenario.platform)
    primary = run_install_variant(scenario, scenario.install_command, env, equivalence_dir / primary_style)
    alternate_result = run_install_variant(scenario, alternate, env, equivalence_dir / alternate_style)
    same_effects = primary["state"] == alternate_result["state"]
    passed = bool(primary["passed"] and alternate_result["passed"] and same_effects)
    report = {
        "status": "runnable",
        "passed": passed,
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
    universal_uninstall_scenarios_func=None,
    run_universal_uninstall_scenario_func=None,
    run_purge_scenario_func=None,
) -> scenario_lifecycle.ScenarioLifecycleHooks:
    return scenario_lifecycle.ScenarioLifecycleHooks(
        output=OUTPUT,
        roots=ROOTS,
        project=PROJECT,
        user_cwd=USER_CWD,
        utc_timestamp=utc_timestamp,
        root_path=root_path,
        reset_sandbox_dirs=reset_sandbox_dirs,
        seed_user_owned_content=seed_user_owned_content,
        write_file_manifest=write_file_manifest,
        run_capture=run_capture,
        scenario_file_state=scenario_file_state,
        assert_expected_files=assert_expected_files,
        assert_scope_boundaries=assert_scope_boundaries,
        assert_no_unexpected_graphify_files=assert_no_unexpected_graphify_files,
        copy_generated_files=copy_generated_files,
        assert_idempotent_state=assert_idempotent_state,
        seed_stale_skill_sidecars=seed_stale_skill_sidecars,
        assert_installed_skill_sidecars=assert_installed_skill_sidecars,
        assert_uninstalled=assert_uninstalled,
        run_equivalence_check=run_equivalence_check,
        risk_report=risk_report,
        command_artifact_summary=command_artifact_summary,
        combined_status=combined_status,
        known_status_values=known_status_values,
        expected_generated_relative_keys=expected_generated_relative_keys,
        check_record=check_record,
        scenario_registry=SCENARIO_REGISTRY,
        platform_scenarios=platform_scenarios,
        run_scenario_func=run_scenario_func,
        universal_uninstall_scenarios_func=universal_uninstall_scenarios_func,
        run_universal_uninstall_scenario_func=run_universal_uninstall_scenario_func,
        run_purge_scenario_func=run_purge_scenario_func,
    )


def scenario_artifact_dir(scenario_name: str) -> Path:
    return scenario_lifecycle.scenario_artifact_dir(scenario_name, hooks=scenario_lifecycle_hooks())


def prepare_scenario_run(scenario: Scenario, env: dict[str, str], *, scenario_name: str | None = None) -> ScenarioRunContext:
    return scenario_lifecycle.prepare_scenario_run(scenario, env, hooks=scenario_lifecycle_hooks(), scenario_name=scenario_name)


scenario_duration_ms = scenario_lifecycle.scenario_duration_ms
write_scenario_artifacts = scenario_lifecycle.write_scenario_artifacts


def scenario_result_record(
    context: ScenarioRunContext,
    *,
    scenario_name: str,
    platform_name: str,
    scope: str,
    passed: bool,
    risks: dict[str, object],
    reproduction_command: tuple[str, ...],
    command_artifact_dir: Path,
) -> dict[str, object]:
    return scenario_lifecycle.scenario_result_record(
        context,
        hooks=scenario_lifecycle_hooks(),
        scenario_name=scenario_name,
        platform_name=platform_name,
        scope=scope,
        passed=passed,
        risks=risks,
        reproduction_command=reproduction_command,
        command_artifact_dir=command_artifact_dir,
    )


def run_initial_install(context: ScenarioRunContext) -> StandardScenarioStages:
    return scenario_lifecycle.run_initial_install(context, hooks=scenario_lifecycle_hooks())


def run_repeat_install(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario_lifecycle.run_repeat_install(context, stages, hooks=scenario_lifecycle_hooks())


def run_stale_sidecar_repair(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario_lifecycle.run_stale_sidecar_repair(context, stages, hooks=scenario_lifecycle_hooks())


def run_uninstall_stage(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario_lifecycle.run_uninstall_stage(context, stages, hooks=scenario_lifecycle_hooks())


def run_equivalence_stage(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario_lifecycle.run_equivalence_stage(context, stages, hooks=scenario_lifecycle_hooks())


standard_scenario_checks = scenario_lifecycle.standard_scenario_checks
standard_scenario_command_ok = scenario_lifecycle.standard_scenario_command_ok


def finalize_standard_scenario(context: ScenarioRunContext, stages: StandardScenarioStages) -> dict[str, object]:
    return scenario_lifecycle.finalize_standard_scenario(context, stages, hooks=scenario_lifecycle_hooks())


def run_scenario(scenario: Scenario, env: dict[str, str]) -> dict[str, object]:
    return scenario_lifecycle.run_scenario(scenario, env, hooks=scenario_lifecycle_hooks())


def run_universal_uninstall_scenario(scope: str, scenarios: list[Scenario], env: dict[str, str]) -> dict[str, object]:
    return scenario_lifecycle.run_universal_uninstall_scenario(scope, scenarios, env, hooks=scenario_lifecycle_hooks())


def run_purge_scenario(env: dict[str, str]) -> dict[str, object]:
    return scenario_lifecycle.run_purge_scenario(env, hooks=scenario_lifecycle_hooks())


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
    return scenario_lifecycle.universal_uninstall_scenarios(platforms, scope, hooks=scenario_lifecycle_hooks())


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    return scenario_lifecycle.run_matrix_scenarios(
        platforms,
        scope,
        env,
        hooks=scenario_lifecycle_hooks(
            run_scenario_func=run_scenario,
            universal_uninstall_scenarios_func=universal_uninstall_scenarios,
            run_universal_uninstall_scenario_func=run_universal_uninstall_scenario,
            run_purge_scenario_func=run_purge_scenario,
        ),
        fail_fast_scenarios=fail_fast_scenarios,
    )


def preflight() -> dict[str, object]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PROJECT.mkdir(parents=True, exist_ok=True)
    HOME.mkdir(parents=True, exist_ok=True)
    USER_CWD.mkdir(parents=True, exist_ok=True)
    checks = {
        "home": str(HOME),
        "xdg_config_home": str(XDG_CONFIG_HOME),
        "project": str(PROJECT),
        "repo_mount": str(REPO_MOUNT),
        "output": str(OUTPUT),
        "home_is_sandbox": str(HOME) == "/tmp/graphify-home",
        "xdg_is_sandbox": str(XDG_CONFIG_HOME) == "/tmp/graphify-home/.config",
        "project_is_sandbox": str(PROJECT) == "/tmp/graphify-project",
        "repo_mount_exists": REPO_MOUNT.is_dir(),
        "repo_mount_read_only": probe_read_only(REPO_MOUNT) if REPO_MOUNT.exists() else False,
    }
    (OUTPUT / "preflight.json").write_text(json.dumps(checks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all(bool(checks[key]) for key in ("home_is_sandbox", "xdg_is_sandbox", "project_is_sandbox", "repo_mount_exists", "repo_mount_read_only")):
        raise RuntimeError(f"sandbox invariant failed: {checks}")
    return checks


def selected_scenarios(args: argparse.Namespace) -> list[Scenario]:
    platforms = selected_platforms(args)
    scenarios: list[Scenario] = []
    for platform_name in platforms:
        scenarios.extend(platform_scenarios(platform_name, args.scope))
    return scenarios


def selected_platforms(args: argparse.Namespace) -> list[str]:
    return SCENARIO_REGISTRY.selected_platforms(all_platforms=args.all, platform_name=args.platform)


def selected_scopes(scope: str) -> list[str]:
    return SCENARIO_REGISTRY.selected_scopes(scope)


def platform_coverage_records(platforms: list[str], scope: str) -> list[dict[str, object]]:
    return SCENARIO_REGISTRY.coverage_records(platforms, scope)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = sandbox_env()
    preflight_data = preflight()
    src_data = copy_source_tree(args.copy_source)
    package_data = install_graphify(env)
    platforms = selected_platforms(args)
    scenarios = selected_scenarios(args)

    results = run_matrix_scenarios(platforms, args.scope, env, fail_fast_scenarios=args.fail_fast_scenarios)
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed

    coverage = platform_coverage_records(platforms, args.scope)
    unsupported = sum(1 for record in coverage if record["status"] == "unsupported")
    manifest = {
        "harness_version": HARNESS_VERSION,
        "python_version": sys.version,
        "os_release": read_os_release(),
        "architecture": platform_mod.machine(),
        "graphify_version": package_data.get("version"),
        "package_install": package_data,
        "source_snapshot": src_data,
        "preflight": preflight_data,
        "target_runtime_verification": {
            "performed": False,
            "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
        },
        "platform_coverage": coverage,
        "platform_coverage_summary": {
            "registered_platform_count": len(platforms),
            "requested_scope": args.scope,
            "runnable_scope_count": len(scenarios),
            "universal_scenario_count": max(0, len(results) - len(scenarios)),
            "unsupported_scope_count": unsupported,
        },
        "windows_validation": default_windows_validation_status(),
        "scenario_count": len(results),
        "graphify_file_effect_pass_count": passed,
        "graphify_file_effect_fail_count": failed,
        "pass_count": passed,
        "fail_count": failed,
        "results": results,
        "risk_status_values": known_status_values(),
    }
    write_manifest_json(OUTPUT / "manifest.json", manifest)
    write_report_md(OUTPUT / "report.md", manifest)
    reports.print_summary(OUTPUT, passed=passed, failed=failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
