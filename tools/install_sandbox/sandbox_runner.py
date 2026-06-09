#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import platform as platform_mod
import re
import shutil
import shlex
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, cast

try:
    from .platform_specs import (
        ALL_PLATFORMS,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SANDBOX_PLATFORM_SPECS,
        SIMULATED_LINUX_LAYOUT_NOTE,
        ExpectedPath,
        PlatformSpec,
        Scenario,
        ScopeSpec,
        direct_install_command,
        direct_uninstall_command,
        equivalence_status,
        equivalent_install_command,
        generic_install_command,
        make_scenario,
        platform_scenarios,
        platform_spec,
        project_skill,
        risk_notes,
        sandbox_platform_specs,
        unsupported_scope_reason,
        user_skill,
    )
except ImportError:
    from platform_specs import (
        ALL_PLATFORMS,
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        SANDBOX_PLATFORM_SPECS,
        SIMULATED_LINUX_LAYOUT_NOTE,
        ExpectedPath,
        PlatformSpec,
        Scenario,
        ScopeSpec,
        direct_install_command,
        direct_uninstall_command,
        equivalence_status,
        equivalent_install_command,
        generic_install_command,
        make_scenario,
        platform_scenarios,
        platform_spec,
        project_skill,
        risk_notes,
        sandbox_platform_specs,
        unsupported_scope_reason,
        user_skill,
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
USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"
GRAPHIFY_MARKER = "## graphify"
RISK_GRAPHIFY_VERIFIED = "graphify_install_verified"
RISK_GRAPHIFY_FAILED = "graphify_install_failed"
COMMAND_TIMEOUTS = {
    "package_install": 600,
    "graphify_version": 60,
    "installer": 120,
    "precondition": 60,
}
USER_CONTENT_PRESERVING_RELATIVES = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude/CLAUDE.md",
    ".github/copilot-instructions.md",
}

WINDOWS_VALIDATION_TARGETS = (
    "windows payload file-effect simulation",
    "antigravity remapping to antigravity-windows",
    "Windows-specific skill payload and references generation",
    "payload consistency for explicit Windows platform selection",
)
COPY_EXCLUDES = (
    ".git",
    ".kilo",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "graphify-out",
    "sandbox-out",
    "tools/install_sandbox/out",
    "build",
    "dist",
    "*.egg-info",
)
GENERATED_COPY_EXCLUDES = (
    ".local",
    ".cache",
    "__pycache__",
    ".pytest_cache",
)
MANIFEST_PRUNE_DIRS = set(GENERATED_COPY_EXCLUDES) | {".mypy_cache", ".ruff_cache", "node_modules"}


@dataclass(frozen=True)
class ScenarioRunContext:
    scenario: Scenario
    env: dict[str, str]
    artifact_dir: Path
    cwd: Path
    started_at: str
    started_monotonic: float


@dataclass
class StandardScenarioStages:
    install_1: subprocess.CompletedProcess[str]
    state_after_install: dict[str, dict[str, object]]
    install_checks: list[dict[str, object]]
    scope_checks: list[dict[str, object]]
    unexpected_install_checks: list[dict[str, object]]
    install_2: subprocess.CompletedProcess[str] | None = None
    idempotency_checks: list[dict[str, object]] = field(default_factory=list)
    stale_sidecar_repair_seeded: list[dict[str, object]] = field(default_factory=list)
    stale_sidecar_repair_result: subprocess.CompletedProcess[str] | None = None
    stale_sidecar_repair_checks: list[dict[str, object]] = field(default_factory=list)
    uninstall_result: subprocess.CompletedProcess[str] | None = None
    uninstall_checks: list[dict[str, object]] = field(default_factory=list)
    unexpected_uninstall_checks: list[dict[str, object]] = field(default_factory=list)
    equivalence_checks: list[dict[str, object]] = field(default_factory=list)
    state_after_repeat: dict[str, dict[str, object]] = field(default_factory=dict)


ROOTS = {
    "home": HOME,
    "project": PROJECT,
    "user_cwd": USER_CWD,
}


def scenario_id(platform: str, scope: str) -> str:
    raw = f"{platform}-{scope}".lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "-", raw)
    safe = re.sub(r"[-_.]{2,}", "-", safe).strip(".-_")
    return safe or "scenario"


def root_path(root: str) -> Path:
    try:
        return ROOTS[root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root}") from exc


def expected_path(entry: ExpectedPath) -> Path:
    return root_path(entry.root) / entry.relative


def is_skill_expected(entry: ExpectedPath) -> bool:
    return Path(entry.relative).name == "SKILL.md"


def skill_dir_for_entry(entry: ExpectedPath) -> Path:
    return expected_path(entry).parent


def skill_relative_dir(entry: ExpectedPath) -> Path:
    return Path(entry.relative).parent


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


def skill_assertion_record(entry: ExpectedPath, relative: Path, ok: bool, detail: str) -> dict[str, object]:
    return check_record(root_path(entry.root) / relative, ok, detail, root=entry.root, relative=relative)


def installed_reference_names(refs_dir: Path) -> list[str]:
    if not refs_dir.is_dir():
        return []
    return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())


def skill_reference_pointers(skill_text: str) -> list[str]:
    return sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)\b", skill_text)))


def check_skill_version(entry: ExpectedPath) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry)
    relative_dir = skill_relative_dir(entry)
    version_path = skill_dir / ".graphify_version"
    version_relative = relative_dir / ".graphify_version"
    expected_version = expected_graphify_version()
    if version_path.exists():
        actual_version = version_path.read_text(encoding="utf-8", errors="replace").strip()
        version_ok = actual_version == expected_version
        version_detail = f"actual={actual_version}; expected={expected_version}"
    else:
        version_ok = False
        version_detail = f"missing; expected={expected_version}"
    return skill_assertion_record(entry, version_relative, version_ok, version_detail)


def check_references_tmp_absent(entry: ExpectedPath) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry)
    relative_dir = skill_relative_dir(entry)
    refs_tmp = skill_dir / "references.tmp"
    return skill_assertion_record(
        entry,
        relative_dir / "references.tmp",
        not refs_tmp.exists(),
        "absent" if not refs_tmp.exists() else "present",
    )


def check_packaged_references(scenario: Scenario, entry: ExpectedPath) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry)
    relative_dir = skill_relative_dir(entry)
    refs_dir = skill_dir / "references"
    refs_relative = relative_dir / "references"
    expected_names = packaged_reference_names(scenario.platform)

    if expected_names is None:
        refs_ok = not refs_dir.exists()
        refs_detail = "no_packaged_references; references_absent" if refs_ok else "no_packaged_references; references_present"
    elif not refs_dir.exists():
        refs_ok = False
        refs_detail = f"references_missing; expected_names={expected_names}"
    elif not refs_dir.is_dir():
        refs_ok = False
        refs_detail = f"references_not_directory; expected_names={expected_names}"
    else:
        actual_names = installed_reference_names(refs_dir)
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        refs_ok = not missing and not extra
        refs_detail = f"actual_names={actual_names}; expected_names={expected_names}; missing={missing}; extra={extra}"
    return skill_assertion_record(entry, refs_relative, refs_ok, refs_detail)


def check_skill_reference_pointers(entry: ExpectedPath, skill_text: str) -> dict[str, object]:
    mentions_references = "references/" in skill_text
    pointers = skill_reference_pointers(skill_text)
    refs_dir = skill_dir_for_entry(entry) / "references"
    if mentions_references and not refs_dir.is_dir():
        pointer_ok = False
        pointer_detail = f"references_missing; skill_mentions_references=true; pointers={pointers}"
    elif pointers:
        missing_pointers = [name for name in pointers if not (refs_dir / name).is_file()]
        pointer_ok = not missing_pointers
        pointer_detail = f"pointers={pointers}; missing={missing_pointers}"
    else:
        pointer_ok = True
        pointer_detail = "no_reference_pointers"
    return skill_assertion_record(entry, Path(entry.relative), pointer_ok, pointer_detail)


def assert_installed_skill_sidecar(scenario: Scenario, entry: ExpectedPath) -> list[dict[str, object]]:
    if not is_skill_expected(entry):
        return []

    skill_path = expected_path(entry)
    skill_text = skill_path.read_text(encoding="utf-8", errors="replace") if skill_path.is_file() else ""
    return [
        check_skill_version(entry),
        check_references_tmp_absent(entry),
        check_packaged_references(scenario, entry),
        check_skill_reference_pointers(entry, skill_text),
    ]


def assert_installed_skill_sidecars(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        checks.extend(assert_installed_skill_sidecar(scenario, entry))
    return checks


def progressive_skill_entries(scenario: Scenario) -> list[ExpectedPath]:
    entries: list[ExpectedPath] = []
    for entry in scenario.expected:
        if is_skill_expected(entry) and packaged_reference_names(scenario.platform) is not None:
            entries.append(entry)
    return entries


def seed_stale_skill_sidecars(scenario: Scenario) -> list[dict[str, object]]:
    seeded: list[dict[str, object]] = []
    for entry in progressive_skill_entries(scenario):
        skill_dir = skill_dir_for_entry(entry)
        relative_dir = skill_relative_dir(entry)
        refs_dir = skill_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        stale_ref = refs_dir / "stale-sandbox-fragment.md"
        stale_ref.write_text("stale sandbox reference fragment\n", encoding="utf-8")
        seeded.append(skill_assertion_record(entry, relative_dir / "references" / stale_ref.name, True, "seeded_stale_reference_fragment"))

        refs_tmp = skill_dir / "references.tmp"
        refs_tmp.mkdir(parents=True, exist_ok=True)
        partial = refs_tmp / "partial.md"
        partial.write_text("partial staged reference fragment\n", encoding="utf-8")
        seeded.append(skill_assertion_record(entry, relative_dir / "references.tmp" / partial.name, True, "seeded_staged_reference_fragment"))
    return seeded


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


def timeout_for(command_class: str, timeout_seconds: int | None = None) -> int:
    return timeout_seconds if timeout_seconds is not None else COMMAND_TIMEOUTS.get(command_class, COMMAND_TIMEOUTS["installer"])


def timeout_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def command_display(command: Iterable[str]) -> tuple[list[str], str]:
    command_list = list(command)
    return command_list, shlex.join(command_list)


def write_command_start_artifacts(artifact_dir: Path, command_text: str, env: dict[str, str]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "command.txt").write_text(command_text + "\n", encoding="utf-8")
    (artifact_dir / "env.json").write_text(json.dumps({k: env.get(k, "") for k in sorted(("HOME", "XDG_CONFIG_HOME", "PATH", "GRAPHIFY_PROJECT"))}, indent=2) + "\n", encoding="utf-8")


def execute_command(command_list: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[subprocess.CompletedProcess[str], bool]:
    try:
        return subprocess.run(command_list, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout), False
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command_list, 127, "", str(exc)), False
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command_list, 124, timeout_text(exc.stdout), timeout_text(exc.stderr) or f"timed out after {timeout} seconds"), True


def command_result_metadata(
    *,
    command_list: list[str],
    command_text: str,
    command_class: str,
    cwd: Path,
    started_at: str,
    duration_ms: int,
    exit_code: int,
    timeout: int,
    timed_out: bool,
) -> dict[str, object]:
    return {
        "command": command_list,
        "command_display": command_text,
        "command_class": command_class,
        "cwd": str(cwd),
        "started_at": started_at,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
    }


def write_command_result_artifacts(artifact_dir: Path, result: subprocess.CompletedProcess[str], metadata: dict[str, object]) -> None:
    (artifact_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    (artifact_dir / "exit-code.txt").write_text(f"{result.returncode}\n", encoding="utf-8")
    (artifact_dir / "command-result.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "transcript.txt").write_text(
        f"$ {metadata['command_display']}\n[command-class]\n{metadata['command_class']}\n[timeout-seconds]\n{metadata['timeout_seconds']}\n[started-at]\n{metadata['started_at']}\n[duration-ms]\n{metadata['duration_ms']}\n[timed-out]\n{str(metadata['timed_out']).lower()}\n\n[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}\n[exit-code]\n{result.returncode}\n",
        encoding="utf-8",
    )


def attach_command_metadata(result: subprocess.CompletedProcess[str], metadata: dict[str, object]) -> None:
    result.started_at = metadata["started_at"]  # type: ignore[attr-defined]
    result.duration_ms = metadata["duration_ms"]  # type: ignore[attr-defined]
    result.timed_out = metadata["timed_out"]  # type: ignore[attr-defined]
    result.timeout_seconds = metadata["timeout_seconds"]  # type: ignore[attr-defined]
    result.command_class = metadata["command_class"]  # type: ignore[attr-defined]


def run_capture(
    command: Iterable[str],
    *,
    cwd: Path,
    env: dict[str, str],
    artifact_dir: Path | None = None,
    command_class: str = "installer",
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command_list, command_text = command_display(command)
    timeout = timeout_for(command_class, timeout_seconds)
    started_at = utc_timestamp()
    start = time.monotonic()
    if artifact_dir is not None:
        write_command_start_artifacts(artifact_dir, command_text, env)
    result, timed_out = execute_command(command_list, cwd=cwd, env=env, timeout=timeout)
    duration_ms = int((time.monotonic() - start) * 1000)
    metadata = command_result_metadata(
        command_list=command_list,
        command_text=command_text,
        command_class=command_class,
        cwd=cwd,
        started_at=started_at,
        duration_ms=duration_ms,
        exit_code=result.returncode,
        timeout=timeout,
        timed_out=timed_out,
    )
    if artifact_dir is not None:
        write_command_result_artifacts(artifact_dir, result, metadata)
    attach_command_metadata(result, metadata)
    return result


def pruned_file_walk(base: Path) -> Iterable[Path]:
    if not base.exists():
        return
    for root, dirs, files in os.walk(base):
        root_path_obj = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in MANIFEST_PRUNE_DIRS)
        for name in sorted(files):
            yield root_path_obj / name


def expected_manifest_relatives(scenario: Scenario, root_name: str) -> set[Path]:
    relatives: set[Path] = set()
    for entry in scenario.expected:
        if entry.root != root_name:
            continue
        relative = Path(entry.relative)
        relatives.add(relative)
        if is_skill_expected(entry):
            skill_dir = relative.parent
            relatives.add(skill_dir / ".graphify_version")
            relatives.add(skill_dir / "references.tmp")
            expected_names = packaged_reference_names(scenario.platform) or []
            for name in expected_names:
                relatives.add(skill_dir / "references" / name)
    return relatives


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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def should_exclude_source_path(relative: str) -> bool:
    parts = Path(relative).parts
    for pattern in COPY_EXCLUDES:
        if "/" in pattern:
            if relative == pattern or relative.startswith(f"{pattern}/"):
                return True
        elif fnmatch.fnmatch(Path(relative).name, pattern) or any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def copy_source_ignore(directory: str, names: list[str]) -> set[str]:
    base = Path(directory)
    ignored = set()
    for name in names:
        path = base / name
        try:
            relative = path.relative_to(REPO_MOUNT).as_posix()
        except ValueError:
            relative = name
        if should_exclude_source_path(relative):
            ignored.add(name)
    return ignored


def repo_relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_MOUNT).as_posix()
    except ValueError:
        return path.name


def validate_source_symlink(src_path: Path) -> str:
    target = os.readlink(src_path)
    target_path = Path(target)
    if target_path.is_absolute():
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path)} points to absolute target {target}")
    resolved_repo = REPO_MOUNT.resolve()
    resolved_target = (src_path.parent / target_path).resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_repo)
    except ValueError as exc:
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path)} points outside repository to {target}") from exc
    if not resolved_target.exists():
        raise RuntimeError(f"unsafe source symlink: {repo_relative(src_path)} points to missing target {target}")
    return target


def validate_source_symlinks_for_copytree() -> None:
    for root, dirs, files in os.walk(REPO_MOUNT):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for name in sorted(dirs):
            path = root_path / name
            relative = repo_relative(path)
            if should_exclude_source_path(relative):
                continue
            if path.is_symlink():
                validate_source_symlink(path)
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in sorted(files):
            path = root_path / name
            if should_exclude_source_path(repo_relative(path)):
                continue
            if path.is_symlink():
                validate_source_symlink(path)


def source_manifest(src: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    file_count = 0
    for path in pruned_file_walk(src):
        file_count += 1
        rel = path.relative_to(src).as_posix()
        if len(files) < 5000:
            entry = {"path": rel, "size": path.stat().st_size}
            if rel in ("pyproject.toml", "graphify/__main__.py"):
                entry["sha256"] = sha256(path)
            files.append(entry)
    return {"root": str(src), "file_count": file_count, "files_sample": files, "excluded_patterns": list(COPY_EXCLUDES)}


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
    result = subprocess.run(["git", "-C", str(REPO_MOUNT), "ls-files", "-z"], text=False, capture_output=True)
    if result.returncode != 0:
        return None
    SRC.mkdir(parents=True, exist_ok=True)
    copied = 0
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        if should_exclude_source_path(rel):
            continue
        src_path = REPO_MOUNT / rel
        dst_path = SRC / rel
        if src_path.is_symlink():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.symlink_to(validate_source_symlink(src_path))
            copied += 1
        elif src_path.is_file():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied += 1
    manifest = source_manifest(SRC)
    manifest["copy_source_mode"] = "auto"
    manifest["snapshot_strategy"] = "git_tracked_files"
    manifest["copied_tracked_file_count"] = copied
    return manifest


def copy_source_tree(copy_source: str = "always") -> dict[str, object]:
    if SRC.exists():
        shutil.rmtree(SRC)
    if copy_source == "auto":
        tracked = copy_tracked_source_tree()
        if tracked is not None:
            return tracked
    validate_source_symlinks_for_copytree()
    shutil.copytree(REPO_MOUNT, SRC, symlinks=True, ignore=copy_source_ignore)
    manifest = source_manifest(SRC)
    manifest["copy_source_mode"] = copy_source
    manifest["snapshot_strategy"] = "copytree_with_exclusions"
    return manifest


def package_search_paths() -> list[Path]:
    paths = [Path(path) for path in sys.path if path]
    paths.extend(HOME.glob(".local/lib/python*/site-packages"))
    return list(dict.fromkeys(path for path in paths if path.exists()))


def direct_url_source_path(direct_url: dict[str, object] | None) -> Path | None:
    if not direct_url:
        return None
    url = direct_url.get("url")
    if not isinstance(url, str):
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "file":
        return None
    return Path(urllib.parse.unquote(parsed.path)).resolve()


def package_metadata_value(metadata: importlib.metadata.PackageMetadata, key: str) -> str | None:
    try:
        value = metadata[key]
    except KeyError:
        return None
    return value or None


def dist_to_metadata(dist: importlib.metadata.Distribution, source: Path) -> dict[str, object]:
    direct_url = None
    direct_text = dist.read_text("direct_url.json")
    if direct_text:
        direct_url = json.loads(direct_text)
    source_path = direct_url_source_path(direct_url)
    return {
        "package_name": package_metadata_value(dist.metadata, "Name") or PACKAGE_NAME,
        "version": dist.version,
        "location": str(Path(str(dist.locate_file(""))).resolve()),
        "direct_url": direct_url,
        "installed_from_copied_source": source_path == source.resolve(),
    }


def metadata_from_dist_info(dist_info: Path, source: Path) -> dict[str, object] | None:
    metadata_path = dist_info / "METADATA"
    if not metadata_path.exists():
        return None
    name = None
    version = None
    for line in metadata_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Name: "):
            name = line.split(": ", 1)[1].strip()
        if line.startswith("Version: "):
            version = line.split(": ", 1)[1].strip()
    if name != PACKAGE_NAME or not version:
        return None
    direct_url = None
    direct_url_path = dist_info / "direct_url.json"
    if direct_url_path.exists():
        direct_url = json.loads(direct_url_path.read_text(encoding="utf-8"))
    source_path = direct_url_source_path(direct_url)
    return {
        "package_name": name,
        "version": version,
        "location": str(dist_info.parent.resolve()),
        "direct_url": direct_url,
        "installed_from_copied_source": source_path == source.resolve(),
    }


def read_installed_package_metadata(package_name: str, source: Path, search_paths: list[Path] | None = None) -> dict[str, object]:
    if search_paths is None:
        try:
            return dist_to_metadata(importlib.metadata.distribution(package_name), source)
        except importlib.metadata.PackageNotFoundError:
            pass

    paths = search_paths or package_search_paths()
    for search_path in paths:
        for dist in importlib.metadata.distributions(path=[str(search_path)]):
            if (package_metadata_value(dist.metadata, "Name") or "").lower() == package_name.lower():
                return dist_to_metadata(dist, source)

    for search_path in paths:
        for dist_info in search_path.glob(f"{package_name}-*.dist-info"):
            metadata = metadata_from_dist_info(dist_info, source)
            if metadata:
                return metadata

    return {
        "package_name": package_name,
        "version": None,
        "location": None,
        "direct_url": None,
        "installed_from_copied_source": False,
    }


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
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def text_snippet(path: Path, limit: int = 500) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def command_artifact_summary(artifact_dir: Path) -> dict[str, object]:
    result = read_json_object(artifact_dir / "command-result.json")
    command = result.get("command")
    command_text = str(result.get("command_display") or (shlex.join([str(part) for part in command]) if isinstance(command, list) else text_snippet(artifact_dir / "command.txt", 1000)))
    return {
        "command": command_text,
        "command_class": result.get("command_class"),
        "started_at": result.get("started_at"),
        "duration_ms": result.get("duration_ms"),
        "exit_code": result.get("exit_code"),
        "timeout_seconds": result.get("timeout_seconds"),
        "timed_out": result.get("timed_out"),
        "transcript_path": artifact_relpath(artifact_dir / "transcript.txt"),
        "stdout_snippet": text_snippet(artifact_dir / "stdout.txt"),
        "stderr_snippet": text_snippet(artifact_dir / "stderr.txt"),
    }


def status_label(result: dict[str, object]) -> str:
    if "overall_status" in result:
        return str(result["overall_status"])
    if result.get("passed") is True:
        return RISK_GRAPHIFY_VERIFIED
    return "graphify_install_failed"


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|")


def md_code(value: object) -> str:
    text = "" if value is None else str(value)
    return "`" + text.replace("`", "'") + "`"


def md_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(md_cell(cell) for cell in cells) + " |"


def md_separator(column_count: int, *, right_align: Iterable[int] = ()) -> str:
    aligned = set(right_align)
    return "|" + "|".join("---:" if index in aligned else "---" for index in range(column_count)) + "|"


def md_table(headers: Iterable[str], rows: Iterable[Iterable[object]], *, right_align: Iterable[int] = ()) -> list[str]:
    header_list = list(headers)
    lines = [md_row(header_list), md_separator(len(header_list), right_align=right_align)]
    lines.extend(md_row(row) for row in rows)
    return lines


def object_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def object_dicts(value: object) -> list[dict[str, object]]:
    return [object_dict(item) for item in object_list(value) if isinstance(item, dict)]


def check_record(path: Path | str, ok: bool, detail: str, *, root: str | None = None, relative: str | Path | None = None, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


def render_report_md(manifest: dict[str, object]) -> str:
    package = object_dict(manifest.get("package_install"))
    preflight_data = object_dict(manifest.get("preflight"))
    os_release = object_dict(manifest.get("os_release"))
    source_snapshot = object_dict(manifest.get("source_snapshot"))
    results = object_dicts(manifest.get("results"))
    coverage = object_dicts(manifest.get("platform_coverage"))
    risk_status_values = object_list(manifest.get("risk_status_values")) or list(known_status_values())

    lines: list[str] = ["# Graphify Install Sandbox Report", ""]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Graphify file effects: {manifest.get('graphify_file_effect_pass_count', manifest.get('pass_count', 0))} passed, {manifest.get('graphify_file_effect_fail_count', manifest.get('fail_count', 0))} failed.",
            "- Target runtime verification: not performed by this Tier 1 file-effect sandbox.",
            f"- Scenario count: {manifest.get('scenario_count', len(results))}.",
            f"- Artifacts: {md_code('manifest.json')}, {md_code('preflight.json')}, {md_code('package-install/')}, {md_code('scenarios/')}.",
            "",
            "## Environment",
            "",
            *md_table(
                ["Field", "Value"],
                [
                    ("OS", os_release.get("PRETTY_NAME") or os_release.get("NAME")),
                    ("Architecture", manifest.get("architecture")),
                    ("Python", manifest.get("python_version")),
                    ("Graphify version", manifest.get("graphify_version")),
                    ("Install mode", package.get("install_mode")),
                    ("Package name", package.get("package_name")),
                    ("Install location", package.get("location")),
                    ("Installed from copied source", package.get("installed_from_copied_source")),
                    ("Source root", source_snapshot.get("root")),
                    ("Sandbox project", preflight_data.get("project")),
                ],
            ),
            "",
            "## Status Vocabulary",
            "",
        ]
    )
    for status in risk_status_values:
        lines.append(f"- {md_code(status)}")
    lines.extend(["", "## Scenario Status", ""])
    scenario_rows = []
    for item in results:
        graphify_status = RISK_GRAPHIFY_VERIFIED if item.get("graphify_file_effects_passed", item.get("passed")) else "graphify_install_failed"
        command_artifact = object_dict(item.get("command_artifact"))
        duration = item.get("duration_ms") or command_artifact.get("duration_ms")
        transcript = command_artifact.get("transcript_path") or item.get("transcript_path") or ""
        scenario_rows.append(
            (
                item.get("platform"),
                item.get("scope"),
                item.get("id"),
                graphify_status,
                status_label(item),
                f"{duration} ms" if duration is not None else "",
                transcript,
            )
        )
    lines.extend(md_table(["Platform", "Scope", "Scenario", "Graphify File Effects", "Overall Status", "Duration", "Transcript"], scenario_rows, right_align={5}))

    lines.extend(["", "## Platform Coverage", ""])
    coverage_rows = []
    for record in coverage:
        command = record.get("install_command")
        command_text = shlex.join([str(part) for part in command]) if isinstance(command, list) else record.get("reason", "")
        coverage_rows.append((record.get("platform"), record.get("scope"), record.get("status"), command_text))
    lines.extend(md_table(["Platform", "Scope", "Coverage", "Graphify Installer Command"], coverage_rows))

    lines.extend(["", "## Target Runtime Verification", "", "- Not performed by this sandbox. The report validates Graphify-owned installer file effects only."])

    windows_validation = object_dict(manifest.get("windows_validation")) or default_windows_validation_status()
    lines.extend(
        [
            "",
            "## Windows Validation",
            "",
            f"- Status: {md_code(windows_validation.get('status'))}",
            f"- Evidence: {md_code(windows_validation.get('evidence_path'))}",
            f"- Strategy: {md_cell(windows_validation.get('strategy'))}",
        ]
    )
    notes = object_list(windows_validation.get("notes"))
    targets = object_list(windows_validation.get("targets"))
    for note in notes:
        lines.append(f"- {md_cell(note)}")
    if targets:
        lines.append(f"- Targets: {md_cell(', '.join(str(target) for target in targets))}")

    failures = [item for item in results if item.get("passed") is not True]
    lines.extend(["", "## Failures", ""])
    if failures:
        for item in failures:
            command_artifact = object_dict(item.get("command_artifact"))
            lines.append(f"### {item.get('id')}")
            lines.append("")
            lines.append(f"- Reproduce: {md_code(item.get('reproduction_command') or command_artifact.get('command'))}")
            lines.append(f"- Transcript: {md_code(command_artifact.get('transcript_path') or item.get('transcript_path'))}")
            if command_artifact.get("stdout_snippet"):
                lines.append(f"- stdout: {md_code(command_artifact.get('stdout_snippet'))}")
            if command_artifact.get("stderr_snippet"):
                lines.append(f"- stderr: {md_code(command_artifact.get('stderr_snippet'))}")
            lines.append("")
    else:
        lines.append("- None.")

    lines.extend(["", "## Command Transcripts", ""])
    transcript_rows = []
    for item in results:
        command_artifact = object_dict(item.get("command_artifact"))
        if not command_artifact:
            continue
        transcript_rows.append(
            (
                item.get("id"),
                command_artifact.get("command"),
                command_artifact.get("started_at"),
                command_artifact.get("duration_ms"),
                command_artifact.get("exit_code"),
                command_artifact.get("transcript_path"),
            )
        )
    lines.extend(md_table(["Scenario", "Command", "Started", "Duration", "Exit", "Transcript"], transcript_rows, right_align={3, 4}))

    return "\n".join(lines).rstrip() + "\n"


def write_report_md(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(render_report_md(manifest), encoding="utf-8")


def default_windows_validation_status() -> dict[str, object]:
    return {
        "status": "payload_consistency_only",
        "evidence_path": None,
        "strategy": "Linux Docker validates Windows-named payload consistency only; real Windows runtime/path semantics require separate Windows validation",
        "targets": list(WINDOWS_VALIDATION_TARGETS),
        "notes": [
            "Linux sandbox results for windows and antigravity-windows check packaged payloads, references, and generated file consistency only.",
            "This does not validate Windows Path.home(), PowerShell/cmd entrypoints, cleanup semantics, permissions, or target-app discovery.",
        ],
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


def should_seed_user_content(entry: ExpectedPath) -> bool:
    return bool(entry.marker and entry.relative in USER_CONTENT_PRESERVING_RELATIVES)


def should_seed_stale_graphify_section(entry: ExpectedPath) -> bool:
    return bool(entry.marker == GRAPHIFY_MARKER and entry.relative.endswith((".md", ".mdc")))


def seeded_text(entry: ExpectedPath) -> str:
    if should_seed_stale_graphify_section(entry):
        return (
            f"# User Notes\n\n{USER_SENTINEL}\n\n"
            f"{entry.marker}\n{STALE_GRAPHIFY_SENTINEL}\n\n"
            "## User Section\nThis section should survive Graphify install and uninstall.\n"
        )
    return f"# User Notes\n\n{USER_SENTINEL}\n"


def seed_user_owned_content(scenario: Scenario) -> None:
    for entry in scenario.expected:
        if should_seed_user_content(entry):
            path = expected_path(entry)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(seeded_text(entry), encoding="utf-8")


def expected_kind_status(path: Path, kind: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if kind == "file":
        return path.is_file(), "file" if path.is_file() else "expected_file_but_not_file"
    if kind == "dir":
        return path.is_dir(), "directory" if path.is_dir() else "expected_directory_but_not_directory"
    return True, "exists"


def json_value_contains_marker(value: object, marker: str) -> bool:
    if isinstance(value, dict):
        return any(marker in str(key) or json_value_contains_marker(item, marker) for key, item in value.items())
    if isinstance(value, list):
        return any(json_value_contains_marker(item, marker) for item in value)
    if isinstance(value, str):
        return marker in value
    return False


def graphify_command_hook_present(entry: object, *, matcher: str | None = None, required_fragments: tuple[str, ...] = ("graphify",)) -> bool:
    entry_data = object_dict(entry)
    if matcher is not None and entry_data.get("matcher") != matcher:
        return False
    for hook in object_dicts(entry_data.get("hooks")):
        if hook.get("type") != "command":
            continue
        command = hook.get("command")
        if isinstance(command, str) and all(fragment in command for fragment in required_fragments):
            return True
    return False


def hooks_by_event(data: object, event_name: str) -> list[object]:
    hooks = object_dict(object_dict(data).get("hooks"))
    return object_list(hooks.get(event_name))


def claude_like_settings_status(data: object, schema_name: str) -> tuple[bool, str]:
    pre_tool = hooks_by_event(data, "PreToolUse")
    bash_hook_present = any(graphify_command_hook_present(entry, matcher="Bash") for entry in pre_tool)
    read_glob_hook_present = any(graphify_command_hook_present(entry, matcher="Read|Glob") for entry in pre_tool)
    ok = bash_hook_present and read_glob_hook_present
    return ok, f"valid_json=true; schema={schema_name}; bash_hook_present={bash_hook_present}; read_glob_hook_present={read_glob_hook_present}"


def codex_hooks_status(data: object) -> tuple[bool, str]:
    pre_tool = hooks_by_event(data, "PreToolUse")
    graphify_hook_present = any(graphify_command_hook_present(entry, matcher="Bash", required_fragments=("graphify", "hook-check")) for entry in pre_tool)
    return graphify_hook_present, f"valid_json=true; schema=codex_hooks; graphify_hook_present={graphify_hook_present}"


def gemini_settings_status(data: object) -> tuple[bool, str]:
    before_tool = hooks_by_event(data, "BeforeTool")
    graphify_hook_present = any(graphify_command_hook_present(entry, matcher="read_file|list_directory") for entry in before_tool)
    return graphify_hook_present, f"valid_json=true; schema=gemini_settings; graphify_hook_present={graphify_hook_present}"


def plugin_config_status(data: object, *, schema_name: str, expected_entry: str, allow_file_uri: bool = False) -> tuple[bool, str]:
    plugins = object_list(object_dict(data).get("plugin"))
    plugin_present = False
    for plugin in plugins:
        if not isinstance(plugin, str):
            continue
        if plugin == expected_entry:
            plugin_present = True
            break
        if allow_file_uri and plugin.startswith("file://") and plugin.endswith(expected_entry):
            plugin_present = True
            break
    return plugin_present, f"valid_json=true; schema={schema_name}; plugin_present={plugin_present}"


def platform_json_status(entry: ExpectedPath, data: object) -> tuple[bool, str] | None:
    if entry.relative in (".claude/settings.json", ".codebuddy/settings.json"):
        schema_name = "claude_settings" if entry.relative == ".claude/settings.json" else "codebuddy_settings"
        return claude_like_settings_status(data, schema_name)
    if entry.relative == ".codex/hooks.json":
        return codex_hooks_status(data)
    if entry.relative == ".gemini/settings.json":
        return gemini_settings_status(data)
    if entry.relative == ".kilo/kilo.json":
        return plugin_config_status(data, schema_name="kilo_config", expected_entry=".kilo/plugins/graphify.js", allow_file_uri=True)
    if entry.relative == ".opencode/opencode.json":
        return plugin_config_status(data, schema_name="opencode_config", expected_entry=".opencode/plugins/graphify.js")
    return None


def json_marker_status(path: Path, entry: ExpectedPath) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid_json={exc.msg}"
    except OSError as exc:
        return False, f"json_read_failed={exc}"
    platform_status = platform_json_status(entry, data)
    if platform_status is not None:
        return platform_status
    marker = entry.marker or ""
    marker_present = bool(marker) and json_value_contains_marker(data, marker)
    return marker_present, f"valid_json=true; schema=generic_marker; marker_present={marker_present}"


def text_marker_status(path: Path, entry: ExpectedPath) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    marker_count = text.count(entry.marker or "")
    ok = marker_count == 1
    detail = f"marker_count={marker_count}"
    if USER_SENTINEL in text:
        detail += "; user_content_preserved"
    elif should_seed_user_content(entry):
        ok = False
        detail += "; user_content_missing"
    if should_seed_stale_graphify_section(entry):
        stale_replaced = STALE_GRAPHIFY_SENTINEL not in text
        ok = ok and stale_replaced
        detail += f"; stale_replaced={stale_replaced}"
    return ok, detail


def expected_entry_status(entry: ExpectedPath) -> tuple[bool, str]:
    path = expected_path(entry)
    ok, detail = expected_kind_status(path, entry.kind)
    if not ok or not entry.marker:
        return ok, detail
    if path.suffix == ".json":
        return json_marker_status(path, entry)
    return text_marker_status(path, entry)


def assert_expected_files(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = expected_path(entry)
        ok, detail = expected_entry_status(entry)
        checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
        checks.extend(assert_installed_skill_sidecar(scenario, entry))
    return checks


def uninstalled_entry_status(entry: ExpectedPath) -> tuple[bool, str]:
    path = expected_path(entry)
    if entry.marker and should_seed_user_content(entry):
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            graphify_removed = entry.marker not in text and STALE_GRAPHIFY_SENTINEL not in text
            user_preserved = USER_SENTINEL in text
            return graphify_removed and user_preserved, f"graphify_removed={graphify_removed}; user_content_preserved={user_preserved}"
        return False, "user_content_file_missing"
    if entry.marker and path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        ok = entry.marker not in text and STALE_GRAPHIFY_SENTINEL not in text
        detail = "graphify_removed; user_content_preserved" if USER_SENTINEL in text else "graphify_removed"
        return ok, detail
    ok = not path.exists()
    return ok, "removed" if ok else "still_exists"


def uninstalled_skill_sidecar_checks(entry: ExpectedPath) -> list[dict[str, object]]:
    if not is_skill_expected(entry):
        return []
    skill_dir = skill_dir_for_entry(entry)
    relative_dir = skill_relative_dir(entry)
    checks: list[dict[str, object]] = []
    for sidecar in (".graphify_version", "references", "references.tmp"):
        sidecar_path = skill_dir / sidecar
        sidecar_ok = not sidecar_path.exists()
        checks.append(
            check_record(
                sidecar_path,
                sidecar_ok,
                "removed" if sidecar_ok else "sidecar_still_exists",
                root=entry.root,
                relative=relative_dir / sidecar,
            )
        )
    return checks


def assert_uninstalled(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = expected_path(entry)
        if not entry.remove_on_uninstall:
            continue
        ok, detail = uninstalled_entry_status(entry)
        checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
        checks.extend(uninstalled_skill_sidecar_checks(entry))
    return checks


def expected_generated_relative_keys(scenario: Scenario) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for entry in scenario.expected:
        keys.add((entry.root, entry.relative))
        if is_skill_expected(entry):
            relative_dir = skill_relative_dir(entry)
            keys.add((entry.root, (relative_dir / ".graphify_version").as_posix()))
            keys.add((entry.root, (relative_dir / "references").as_posix()))
            keys.add((entry.root, (relative_dir / "references.tmp").as_posix()))
            for name in packaged_reference_names(scenario.platform) or []:
                keys.add((entry.root, (relative_dir / "references" / name).as_posix()))
    return keys


def assert_no_unexpected_graphify_files(
    scenario: Scenario,
    *,
    phase: str,
    expected_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    expected = expected_generated_relative_keys(scenario) if expected_keys is None else expected_keys
    checks: list[dict[str, object]] = []
    for root_name, root in ROOTS.items():
        if not root.exists():
            continue
        for path in pruned_file_walk(root):
            relative = path.relative_to(root)
            rel = relative.as_posix()
            if should_exclude_generated_path(relative):
                continue
            if (root_name, rel) in expected:
                continue
            if not is_relevant_generated_file(scenario, root_name, relative, path):
                continue
            checks.append(
                check_record(
                    path,
                    False,
                    f"unexpected_graphify_related_file_after_{phase}",
                    root=root_name,
                    relative=rel,
                )
            )
    if not checks:
        checks.append(check_record("unexpected-graphify-files", True, f"none_after_{phase}"))
    return checks


def assert_scope_boundaries(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        allowed = True
        if scenario.scope == "user" and entry.root not in ("home",):
            allowed = "mixed_scope_project_wiring" in scenario.risk_notes
        if scenario.scope == "project" and entry.root not in ("project",):
            allowed = "mixed_scope_global_skill_plus_project_wiring" in scenario.risk_notes
        checks.append(check_record(expected_path(entry), allowed, "allowed_root" if allowed else "unexpected_root"))
    return checks


def file_fingerprint(path: Path, marker: str | None = None) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    if path.is_dir():
        return {"exists": True, "kind": "dir"}
    data = path.read_bytes()
    item: dict[str, object] = {"exists": True, "kind": "file", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if marker:
        text = data.decode("utf-8", errors="replace")
        item["marker_count"] = text.count(marker)
        item["user_content_preserved"] = USER_SENTINEL in text
        item["stale_graphify_present"] = STALE_GRAPHIFY_SENTINEL in text
    return item


def scenario_file_state(scenario: Scenario) -> dict[str, dict[str, object]]:
    state: dict[str, dict[str, object]] = {}
    for entry in scenario.expected:
        key = f"{entry.root}/{entry.relative}"
        state[key] = file_fingerprint(expected_path(entry), entry.marker)
        if not is_skill_expected(entry):
            continue
        skill_dir = skill_dir_for_entry(entry)
        relative_dir = skill_relative_dir(entry)
        sidecar_relatives: set[Path] = {
            relative_dir / ".graphify_version",
            relative_dir / "references",
            relative_dir / "references.tmp",
        }
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            sidecar_relatives.update(relative_dir / "references" / path.name for path in refs_dir.glob("*.md") if path.is_file())
        expected_names = packaged_reference_names(scenario.platform)
        if expected_names:
            sidecar_relatives.update(relative_dir / "references" / name for name in expected_names)
        for relative in sorted(sidecar_relatives, key=lambda item: item.as_posix()):
            state[f"{entry.root}/{relative.as_posix()}"] = file_fingerprint(root_path(entry.root) / relative)
    return state


def assert_idempotent_state(before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for key in sorted(set(before) | set(after)):
        stable = before.get(key) == after.get(key)
        checks.append(check_record(key, stable, "unchanged_after_repeat_install" if stable else "changed_after_repeat_install"))
    return checks


def should_exclude_generated_path(relative: Path) -> bool:
    return any(part in GENERATED_COPY_EXCLUDES for part in relative.parts)


def is_expected_generated_key(scenario: Scenario, root_name: str, relative: Path) -> bool:
    expected = {(entry.root, entry.relative) for entry in scenario.expected}
    return (root_name, relative.as_posix()) in expected


def is_skill_sidecar_relative(scenario: Scenario, root_name: str, relative: Path) -> bool:
    for entry in scenario.expected:
        if root_name != entry.root or not is_skill_expected(entry):
            continue
        skill_rel_dir = skill_relative_dir(entry)
        if relative == skill_rel_dir / ".graphify_version":
            return True
        for sidecar_dir in ("references", "references.tmp"):
            try:
                relative.relative_to(skill_rel_dir / sidecar_dir)
                return True
            except ValueError:
                pass
    return False


def is_adjacent_graphify_version(scenario: Scenario, root_name: str, relative: Path) -> bool:
    return relative.name == ".graphify_version" and any(
        root_name == entry.root and relative.parent.as_posix() == Path(entry.relative).parent.as_posix()
        for entry in scenario.expected
    )


def is_small_text_candidate(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > 1024 * 1024:
        return False
    text_suffixes = {".json", ".js", ".md", ".mdc", ".txt", ""}
    return path.suffix in text_suffixes


def file_mentions_graphify_or_sentinel(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "graphify" in text.lower() or USER_SENTINEL in text


def is_relevant_generated_file(scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
    rel = relative.as_posix()
    if is_expected_generated_key(scenario, root_name, relative):
        return True
    if is_skill_sidecar_relative(scenario, root_name, relative):
        return True
    if is_adjacent_graphify_version(scenario, root_name, relative):
        return True
    if "graphify" in rel.lower():
        return True
    if not is_small_text_candidate(path):
        return False
    return file_mentions_graphify_or_sentinel(path)


def copy_generated_files(scenario: Scenario, artifact_dir: Path) -> None:
    out = artifact_dir / "generated-files"
    if out.exists():
        shutil.rmtree(out)
    for root_name, root in ROOTS.items():
        if not root.exists():
            continue
        target = out / root_name
        for path in pruned_file_walk(root):
            rel = path.relative_to(root)
            if should_exclude_generated_path(rel) or not is_relevant_generated_file(scenario, root_name, rel, path):
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


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


def scenario_artifact_dir(scenario_name: str) -> Path:
    return OUTPUT / "scenarios" / scenario_name


def prepare_scenario_run(scenario: Scenario, env: dict[str, str], *, scenario_name: str | None = None) -> ScenarioRunContext:
    started_at = utc_timestamp()
    started_monotonic = time.monotonic()
    reset_sandbox_dirs()
    artifact_dir = scenario_artifact_dir(scenario_name or scenario_id(scenario.platform, scenario.scope))
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return ScenarioRunContext(
        scenario=scenario,
        env=env,
        artifact_dir=artifact_dir,
        cwd=root_path(scenario.cwd_root),
        started_at=started_at,
        started_monotonic=started_monotonic,
    )


def scenario_duration_ms(context: ScenarioRunContext) -> int:
    return int((time.monotonic() - context.started_monotonic) * 1000)


def write_scenario_artifacts(artifact_dir: Path, assertions: dict[str, object], risks: dict[str, object]) -> None:
    (artifact_dir / "assertions.json").write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "risk.json").write_text(json.dumps(risks, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    return {
        "id": scenario_name,
        "platform": platform_name,
        "scope": scope,
        "started_at": context.started_at,
        "duration_ms": scenario_duration_ms(context),
        "reproduction_command": shlex.join(reproduction_command),
        "command_artifact": command_artifact_summary(command_artifact_dir),
        "overall_status": combined_status(passed),
        "graphify_file_effects_passed": passed,
        "passed": passed,
        "risks": risks["statuses"],
    }


def run_initial_install(context: ScenarioRunContext) -> StandardScenarioStages:
    scenario = context.scenario
    seed_user_owned_content(scenario)
    write_file_manifest(context.artifact_dir / "before-install-files.json", ROOTS, scenario=scenario)

    install_1 = run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir, command_class="installer")
    state_after_install = scenario_file_state(scenario)
    install_checks = assert_expected_files(scenario)
    scope_checks = assert_scope_boundaries(scenario)
    unexpected_install_checks = assert_no_unexpected_graphify_files(scenario, phase="install")
    write_file_manifest(context.artifact_dir / "after-install-files.json", ROOTS, scenario=scenario)
    copy_generated_files(scenario, context.artifact_dir)
    return StandardScenarioStages(
        install_1=install_1,
        state_after_install=state_after_install,
        install_checks=install_checks,
        scope_checks=scope_checks,
        unexpected_install_checks=unexpected_install_checks,
    )


def run_repeat_install(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario = context.scenario
    stages.install_2 = run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "repeat-install", command_class="installer")
    stages.state_after_repeat = scenario_file_state(scenario)
    stages.idempotency_checks = assert_idempotent_state(stages.state_after_install, stages.state_after_repeat)
    stages.idempotency_checks.extend(assert_no_unexpected_graphify_files(scenario, phase="repeat_install"))
    write_file_manifest(context.artifact_dir / "after-repeat-install-files.json", ROOTS, scenario=scenario)


def run_stale_sidecar_repair(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario = context.scenario
    stages.stale_sidecar_repair_seeded = seed_stale_skill_sidecars(scenario)
    if not stages.stale_sidecar_repair_seeded:
        return
    stages.stale_sidecar_repair_result = run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "stale-sidecar-repair", command_class="installer")
    if stages.stale_sidecar_repair_result.returncode == 0:
        stages.stale_sidecar_repair_checks = assert_installed_skill_sidecars(scenario)
        stages.stale_sidecar_repair_checks.extend(assert_no_unexpected_graphify_files(scenario, phase="stale_sidecar_repair"))
    write_file_manifest(context.artifact_dir / "after-stale-sidecar-repair-files.json", ROOTS, scenario=scenario)


def run_uninstall_stage(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    scenario = context.scenario
    if not scenario.uninstall_command:
        return
    stages.uninstall_result = run_capture(scenario.uninstall_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "uninstall", command_class="installer")
    stages.uninstall_checks = assert_uninstalled(scenario)
    stages.unexpected_uninstall_checks = assert_no_unexpected_graphify_files(scenario, phase="uninstall")
    write_file_manifest(context.artifact_dir / "after-uninstall-files.json", ROOTS, scenario=scenario)


def run_equivalence_stage(context: ScenarioRunContext, stages: StandardScenarioStages) -> None:
    stages.equivalence_checks = run_equivalence_check(context.scenario, context.env, context.artifact_dir)


def standard_scenario_checks(stages: StandardScenarioStages) -> list[dict[str, object]]:
    return (
        stages.install_checks
        + stages.scope_checks
        + stages.unexpected_install_checks
        + stages.idempotency_checks
        + stages.stale_sidecar_repair_checks
        + stages.uninstall_checks
        + stages.unexpected_uninstall_checks
        + stages.equivalence_checks
    )


def standard_scenario_command_ok(stages: StandardScenarioStages) -> bool:
    return (
        stages.install_1.returncode == 0
        and stages.install_2 is not None
        and stages.install_2.returncode == 0
        and (stages.stale_sidecar_repair_result is None or stages.stale_sidecar_repair_result.returncode == 0)
        and (stages.uninstall_result is None or stages.uninstall_result.returncode == 0)
    )


def finalize_standard_scenario(context: ScenarioRunContext, stages: StandardScenarioStages) -> dict[str, object]:
    scenario = context.scenario
    checks = standard_scenario_checks(stages)
    passed = standard_scenario_command_ok(stages) and all(check["ok"] for check in checks)
    assertions = {
        "scenario": {"platform": scenario.platform, "scope": scenario.scope, "id": scenario_id(scenario.platform, scenario.scope)},
        "passed": passed,
        "install_exit_code": stages.install_1.returncode,
        "repeat_install_exit_code": None if stages.install_2 is None else stages.install_2.returncode,
        "stale_sidecar_repair_exit_code": None if stages.stale_sidecar_repair_result is None else stages.stale_sidecar_repair_result.returncode,
        "stale_sidecar_repair_seeded": stages.stale_sidecar_repair_seeded,
        "stale_sidecar_repair_checks": stages.stale_sidecar_repair_checks,
        "uninstall_exit_code": None if stages.uninstall_result is None else stages.uninstall_result.returncode,
        "state_after_install": stages.state_after_install,
        "state_after_repeat_install": stages.state_after_repeat,
        "generic_direct_equivalence": equivalence_status(scenario),
        "checks": checks,
    }
    risks = risk_report(scenario, passed)
    write_scenario_artifacts(context.artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        scenario_name=scenario_id(scenario.platform, scenario.scope),
        platform_name=scenario.platform,
        scope=scenario.scope,
        passed=passed,
        risks=risks,
        reproduction_command=scenario.install_command,
        command_artifact_dir=context.artifact_dir,
    )


def run_scenario(scenario: Scenario, env: dict[str, str]) -> dict[str, object]:
    context = prepare_scenario_run(scenario, env)
    stages = run_initial_install(context)
    if stages.install_1.returncode == 0:
        run_repeat_install(context, stages)
        if stages.install_2 is not None and stages.install_2.returncode == 0:
            run_stale_sidecar_repair(context, stages)
        run_uninstall_stage(context, stages)
        run_equivalence_stage(context, stages)
    return finalize_standard_scenario(context, stages)


def run_universal_uninstall_scenario(scope: str, scenarios: list[Scenario], env: dict[str, str]) -> dict[str, object]:
    scenario_name = f"universal-uninstall-{scope}"
    runner_scenario = Scenario(
        platform="multiple",
        scope=scope,
        install_command=("graphify", "uninstall", "--project") if scope == "project" else ("graphify", "uninstall"),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=tuple(entry for scenario in scenarios for entry in scenario.expected),
    )
    context = prepare_scenario_run(runner_scenario, env, scenario_name=scenario_name)
    artifact_dir = context.artifact_dir

    for scenario in scenarios:
        seed_user_owned_content(scenario)
    write_file_manifest(artifact_dir / "before-install-files.json", ROOTS)

    install_results = []
    install_checks: list[dict[str, object]] = []
    for scenario in scenarios:
        install_dir = artifact_dir / "installs" / scenario_id(scenario.platform, scenario.scope)
        result = run_capture(scenario.install_command, cwd=root_path(scenario.cwd_root), env=env, artifact_dir=install_dir, command_class="installer")
        scenario_install_checks = assert_expected_files(scenario) + assert_scope_boundaries(scenario)
        install_checks.extend(scenario_install_checks)
        install_results.append(
            {
                "scenario_id": scenario_id(scenario.platform, scenario.scope),
                "command": list(scenario.install_command),
                "exit_code": result.returncode,
                "checks": scenario_install_checks,
            }
        )
    write_file_manifest(artifact_dir / "after-install-files.json", ROOTS, debug_full=True)

    if scope == "project":
        uninstall_command = ("graphify", "uninstall", "--project")
        cwd = PROJECT
    else:
        uninstall_command = ("graphify", "uninstall")
        cwd = USER_CWD
    uninstall_result = run_capture(uninstall_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "uninstall", command_class="installer")
    checks = install_checks + [check for scenario in scenarios for check in assert_uninstalled(scenario)]
    expected_keys = set().union(*(expected_generated_relative_keys(scenario) for scenario in scenarios))
    checks.extend(assert_no_unexpected_graphify_files(runner_scenario, phase="universal_uninstall", expected_keys=expected_keys))
    write_file_manifest(artifact_dir / "after-uninstall-files.json", ROOTS, debug_full=True)
    passed = all(result["exit_code"] == 0 for result in install_results) and uninstall_result.returncode == 0 and all(check["ok"] for check in checks)
    assertions = {
        "scenario": {"id": scenario_name, "scope": scope, "platforms": [scenario.platform for scenario in scenarios]},
        "passed": passed,
        "install_results": install_results,
        "uninstall_command": list(uninstall_command),
        "uninstall_exit_code": uninstall_result.returncode,
        "checks": checks,
    }
    risks = {
        "statuses": [RISK_GRAPHIFY_VERIFIED if passed else RISK_GRAPHIFY_FAILED],
        "notes": ["universal uninstall covers Graphify-owned file effects after multiple installs"],
        "known_status_values": known_status_values(),
    }
    write_scenario_artifacts(artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        scenario_name=scenario_name,
        platform_name="multiple",
        scope=scope,
        passed=passed,
        risks=risks,
        reproduction_command=uninstall_command,
        command_artifact_dir=artifact_dir / "uninstall",
    )


def run_purge_scenario(env: dict[str, str]) -> dict[str, object]:
    scenario_name = "purge-disposable-graphify-out"
    command = ("graphify", "uninstall", "--purge")
    runner_scenario = Scenario(
        platform="purge",
        scope="project",
        install_command=command,
        uninstall_command=None,
        cwd_root="project",
        expected=(),
    )
    context = prepare_scenario_run(runner_scenario, env, scenario_name=scenario_name)
    artifact_dir = context.artifact_dir
    graphify_out = PROJECT / "graphify-out"
    graphify_out.mkdir(parents=True, exist_ok=True)
    (graphify_out / "graph.json").write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    write_file_manifest(artifact_dir / "before-install-files.json", ROOTS)
    result = run_capture(command, cwd=PROJECT, env=env, artifact_dir=artifact_dir / "uninstall-purge", command_class="installer")
    purged = not graphify_out.exists()
    write_file_manifest(artifact_dir / "after-uninstall-files.json", ROOTS)
    checks = [check_record(graphify_out, purged, "purged" if purged else "still_exists")]
    passed = result.returncode == 0 and purged
    assertions = {
        "scenario": {"id": scenario_name, "scope": "project", "platform": "purge"},
        "passed": passed,
        "uninstall_exit_code": result.returncode,
        "checks": checks,
    }
    risks = {
        "statuses": [RISK_GRAPHIFY_VERIFIED if passed else RISK_GRAPHIFY_FAILED],
        "notes": ["purge verified only against disposable sandbox graphify-out state"],
        "known_status_values": known_status_values(),
    }
    write_scenario_artifacts(artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        scenario_name=scenario_name,
        platform_name="purge",
        scope="project",
        passed=passed,
        risks=risks,
        reproduction_command=command,
        command_artifact_dir=artifact_dir / "uninstall-purge",
    )


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
    requested = set(platforms)
    groups: list[tuple[str, list[Scenario]]] = []
    if scope in {"user", "both"}:
        scenarios = [make_scenario(platform_name, "user") for platform_name, spec in sandbox_platform_specs().items() if platform_name in requested and "user" in spec.universal_uninstall_scopes]
        runnable = [scenario for scenario in scenarios if scenario is not None]
        if len(runnable) >= 2:
            groups.append(("user", runnable))
    if scope in {"project", "both"}:
        scenarios = [make_scenario(platform_name, "project") for platform_name, spec in sandbox_platform_specs().items() if platform_name in requested and "project" in spec.universal_uninstall_scopes]
        runnable = [scenario for scenario in scenarios if scenario is not None]
        if len(runnable) >= 2:
            groups.append(("project", runnable))
    return groups


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for scenario in [scenario for platform_name in platforms for scenario in platform_scenarios(platform_name, scope)]:
        result = run_scenario(scenario, env)
        results.append(result)
        if fail_fast_scenarios and result.get("passed") is not True:
            return results
    if any(result.get("passed") is not True for result in results):
        return results
    for universal_scope, scenarios in universal_uninstall_scenarios(platforms, scope):
        result = run_universal_uninstall_scenario(universal_scope, scenarios, env)
        results.append(result)
    if scope in {"project", "both"}:
        result = run_purge_scenario(env)
        results.append(result)
    return results


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
    platforms = ALL_PLATFORMS if args.all else [args.platform]
    unknown = [platform_name for platform_name in platforms if platform_name not in ALL_PLATFORMS]
    if unknown:
        raise RuntimeError(f"unknown sandbox platform(s): {', '.join(unknown)}")
    return platforms


def selected_scopes(scope: str) -> list[str]:
    return ["user", "project"] if scope == "both" else [scope]


def platform_coverage_records(platforms: list[str], scope: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for platform_name in platforms:
        for one_scope in selected_scopes(scope):
            reason = unsupported_scope_reason(platform_name, one_scope)
            scenario = make_scenario(platform_name, one_scope) if reason is None else None
            if scenario is not None:
                records.append(
                    {
                        "platform": platform_name,
                        "scope": one_scope,
                        "status": "runnable",
                        "scenario_id": scenario_id(platform_name, one_scope),
                        "install_command": list(scenario.install_command),
                        "uninstall_command": None if scenario.uninstall_command is None else list(scenario.uninstall_command),
                        "generic_direct_equivalence": equivalence_status(scenario),
                        "risk_notes": list(scenario.risk_notes),
                    }
                )
            else:
                records.append(
                    {
                        "platform": platform_name,
                        "scope": one_scope,
                        "status": "unsupported",
                        "reason": reason or "no sandbox scenario is defined for this platform/scope",
                    }
                )
    return records


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
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_md(OUTPUT / "report.md", manifest)
    print(json.dumps({"passed": passed, "failed": failed, "output": str(OUTPUT), "report": str(OUTPUT / "report.md"), "target_runtime_verification_performed": False}, indent=2), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
