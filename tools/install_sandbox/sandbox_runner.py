#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import platform as platform_mod
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


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
RISK_RUNTIME_VERIFIED = "target_tool_runtime_verified"
RISK_RUNTIME_UNVERIFIED = "risk_unverified_tool_runtime"
RISK_TOOL_UNAVAILABLE = "tool_unavailable_in_docker"
DIRECT_USER_EQUIVALENT_PLATFORMS = {"gemini", "copilot", "devin", "pi"}
DIRECT_PROJECT_EQUIVALENT_PLATFORMS = {
    "claude",
    "gemini",
    "cursor",
    "devin",
    "aider",
    "amp",
    "codex",
    "opencode",
    "claw",
    "droid",
    "trae",
    "trae-cn",
    "hermes",
    "kiro",
    "copilot",
    "pi",
    "antigravity",
}
UNIVERSAL_USER_PLATFORMS = ("gemini", "vscode", "antigravity")
UNIVERSAL_PROJECT_PLATFORMS = ("codex", "claude", "gemini", "cursor", "devin")
USER_CONTENT_PRESERVING_RELATIVES = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude/CLAUDE.md",
    ".github/copilot-instructions.md",
}

ALL_PLATFORMS = [
    "claude",
    "codex",
    "opencode",
    "kilo",
    "gemini",
    "cursor",
    "devin",
    "aider",
    "copilot",
    "vscode",
    "claw",
    "droid",
    "trae",
    "trae-cn",
    "hermes",
    "kiro",
    "pi",
    "antigravity",
    "antigravity-windows",
    "windows",
    "kimi",
    "amp",
]
AGENTS_MD_PLATFORMS = {"aider", "amp", "codex", "opencode", "claw", "droid", "trae", "trae-cn", "hermes"}
SKILL_ONLY_PROJECT_PLATFORMS = {"copilot", "pi", "antigravity", "antigravity-windows", "kimi"}
SIMULATED_LINUX_LAYOUT_PLATFORMS = {"antigravity-windows", "windows"}
WINDOWS_VALIDATION_TARGETS = (
    "windows user/project install file effects",
    "antigravity remapping to antigravity-windows",
    "command entrypoint invocation after package install",
    "Windows-specific skill payload and hook JSON generation",
    "Windows install/uninstall cleanup behavior",
)
PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL = {
    "aider",
    "amp",
    "claude",
    "codex",
    "opencode",
    "claw",
    "droid",
    "trae",
    "trae-cn",
    "hermes",
    "kiro",
    "windows",
    "kimi",
    "antigravity-windows",
}
UNSUPPORTED_SCOPES = {
    ("cursor", "user"): "cursor install writes a project-local .cursor rule in the current working directory; sandbox covers that file effect as project scope",
}
COPY_EXCLUDES = (
    ".git",
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


@dataclass(frozen=True)
class ExpectedPath:
    root: str
    relative: str
    kind: str = "file"
    marker: str | None = None
    remove_on_uninstall: bool = True


@dataclass(frozen=True)
class Scenario:
    platform: str
    scope: str
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[ExpectedPath, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetToolProbe:
    tool: str
    command: tuple[str, ...] | None
    version_command: tuple[str, ...] | None
    credentials_required: bool
    docker_headless_expected: bool
    unavailable_reason: str | None = None
    docs_checked: tuple[str, ...] = field(default_factory=tuple)
    command_kind: str = "discovery"
    timeout_seconds: int = 60


ROOTS = {
    "home": HOME,
    "project": PROJECT,
    "user_cwd": USER_CWD,
}


TOOL_PROBES: dict[str, TargetToolProbe] = {
    "claude": TargetToolProbe(
        tool="claude",
        command=("claude", "--version"),
        version_command=("claude", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://docs.anthropic.com/en/docs/claude-code",),
    ),
    "codex": TargetToolProbe(
        tool="codex",
        command=("npm", "install", "--global", "--prefix", str(HOME / ".local"), "@openai/codex"),
        version_command=("codex", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://github.com/openai/codex",),
        command_kind="install",
        timeout_seconds=300,
    ),
    "opencode": TargetToolProbe(
        tool="opencode",
        command=("opencode", "--version"),
        version_command=("opencode", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://opencode.ai/docs",),
    ),
    "kilo": TargetToolProbe(
        tool="kilo",
        command=("npm", "install", "--global", "--prefix", str(HOME / ".local"), "@kilocode/cli"),
        version_command=("kilo", "--version"),
        credentials_required=False,
        docker_headless_expected=True,
        docs_checked=("https://github.com/Kilo-Org/kilocode",),
        command_kind="install",
        timeout_seconds=300,
    ),
    "gemini": TargetToolProbe(
        tool="gemini",
        command=("gemini", "--version"),
        version_command=("gemini", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://github.com/google-gemini/gemini-cli",),
    ),
    "cursor": TargetToolProbe(
        tool="cursor",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Cursor is a GUI/editor runtime; the Linux sandbox verifies generated file layout only.",
        docs_checked=("https://cursor.com/",),
    ),
    "devin": TargetToolProbe(
        tool="devin",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Devin is a hosted authenticated assistant runtime, not a public headless CLI installed in this sandbox.",
        docs_checked=("https://devin.ai/",),
    ),
    "aider": TargetToolProbe(
        tool="aider",
        command=(sys.executable, "-m", "pip", "install", "--user", "aider-chat"),
        version_command=("aider", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://aider.chat/docs/install.html",),
        command_kind="install",
        timeout_seconds=300,
    ),
    "copilot": TargetToolProbe(
        tool="copilot",
        command=("gh", "copilot", "--version"),
        version_command=("gh", "copilot", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://docs.github.com/en/copilot/how-tos/copilot-cli",),
    ),
    "vscode": TargetToolProbe(
        tool="vscode",
        command=("code", "--version"),
        version_command=("code", "--version"),
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="VS Code/Copilot Chat runtime requires editor installation and authentication; sandbox covers generated files only unless code is preinstalled.",
        docs_checked=("https://code.visualstudio.com/docs/copilot/overview",),
    ),
    "claw": TargetToolProbe(
        tool="claw",
        command=("claw", "--version"),
        version_command=("claw", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://openclaw.ai/",),
    ),
    "droid": TargetToolProbe(
        tool="droid",
        command=("droid", "--version"),
        version_command=("droid", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://factory.ai/",),
    ),
    "trae": TargetToolProbe(
        tool="trae",
        command=("trae", "--version"),
        version_command=("trae", "--version"),
        credentials_required=True,
        docker_headless_expected=False,
        docs_checked=("https://trae.ai/",),
    ),
    "trae-cn": TargetToolProbe(
        tool="trae-cn",
        command=("trae", "--version"),
        version_command=("trae", "--version"),
        credentials_required=True,
        docker_headless_expected=False,
        docs_checked=("https://www.trae.cn/",),
    ),
    "hermes": TargetToolProbe(
        tool="hermes",
        command=("hermes", "--version"),
        version_command=("hermes", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        unavailable_reason="Hermes runtime is not packaged in the base sandbox image; discovery is recorded when attempted.",
    ),
    "kiro": TargetToolProbe(
        tool="kiro",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Kiro is an editor/agent runtime; no headless CLI is installed in this Linux sandbox image.",
        docs_checked=("https://kiro.dev/",),
    ),
    "pi": TargetToolProbe(
        tool="pi",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Pi agent runtime availability is not represented by a public headless CLI in this sandbox.",
    ),
    "antigravity": TargetToolProbe(
        tool="antigravity",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Google Antigravity is a GUI/editor runtime; the Linux sandbox verifies generated file layout only.",
        docs_checked=("https://antigravity.google/",),
    ),
    "antigravity-windows": TargetToolProbe(
        tool="antigravity-windows",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Windows Antigravity behavior is simulated as Linux file-layout coverage; runtime verification requires a real Windows validation path.",
        docs_checked=("https://antigravity.google/",),
    ),
    "windows": TargetToolProbe(
        tool="windows",
        command=None,
        version_command=None,
        credentials_required=True,
        docker_headless_expected=False,
        unavailable_reason="Windows Claude runtime behavior is simulated as Linux file-layout coverage; runtime verification requires a real Windows validation path.",
        docs_checked=("https://docs.anthropic.com/en/docs/claude-code",),
    ),
    "kimi": TargetToolProbe(
        tool="kimi",
        command=("kimi", "--version"),
        version_command=("kimi", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        unavailable_reason="Kimi runtime is not packaged in the base sandbox image; discovery is recorded when attempted.",
    ),
    "amp": TargetToolProbe(
        tool="amp",
        command=("amp", "--version"),
        version_command=("amp", "--version"),
        credentials_required=True,
        docker_headless_expected=True,
        docs_checked=("https://ampcode.com/",),
    ),
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


def expected_graphify_version() -> str:
    return str(graphify_main_module().__version__)


def packaged_references_dir(platform_name: str) -> Path | None:
    graphify_main = graphify_main_module()
    if platform_name == "vscode":
        package_dir = Path(graphify_main.__file__).parent
        bundle = "vscode" if (package_dir / "skill-vscode.md").exists() else "copilot"
        bundle_dir = package_dir / "skills" / bundle
        if not bundle_dir.is_dir():
            return None
        return bundle_dir / "references"
    if platform_name == "gemini" or platform_name in graphify_main._PLATFORM_CONFIG:
        return graphify_main._packaged_skill_refs_dir(platform_name)
    return None


def packaged_reference_names(platform_name: str) -> list[str] | None:
    refs_dir = packaged_references_dir(platform_name)
    if refs_dir is None:
        return None
    if not refs_dir.is_dir():
        return []
    return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())


def skill_assertion_record(entry: ExpectedPath, relative: Path, ok: bool, detail: str) -> dict[str, object]:
    return {"path": str(root_path(entry.root) / relative), "root": entry.root, "relative": relative.as_posix(), "ok": ok, "detail": detail}


def installed_reference_names(refs_dir: Path) -> list[str]:
    if not refs_dir.is_dir():
        return []
    return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())


def skill_reference_pointers(skill_text: str) -> list[str]:
    return sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)\b", skill_text)))


def assert_installed_skill_sidecar(scenario: Scenario, entry: ExpectedPath) -> list[dict[str, object]]:
    if not is_skill_expected(entry):
        return []

    checks: list[dict[str, object]] = []
    skill_path = expected_path(entry)
    skill_dir = skill_path.parent
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
    checks.append(skill_assertion_record(entry, version_relative, version_ok, version_detail))

    refs_tmp = skill_dir / "references.tmp"
    checks.append(
        skill_assertion_record(
            entry,
            relative_dir / "references.tmp",
            not refs_tmp.exists(),
            "absent" if not refs_tmp.exists() else "present",
        )
    )

    skill_text = skill_path.read_text(encoding="utf-8", errors="replace") if skill_path.exists() else ""
    mentions_references = "references/" in skill_text
    pointers = skill_reference_pointers(skill_text)
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
    checks.append(skill_assertion_record(entry, refs_relative, refs_ok, refs_detail))

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
    checks.append(skill_assertion_record(entry, Path(entry.relative), pointer_ok, pointer_detail))
    return checks


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


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    ordered = list(notes)
    if platform_name in SIMULATED_LINUX_LAYOUT_PLATFORMS:
        ordered.append("simulated_linux_file_layout_only")
    return tuple(dict.fromkeys(ordered))


def user_skill(platform_name: str) -> ExpectedPath:
    mapping = {
        "claude": ".claude/skills/graphify/SKILL.md",
        "codex": ".agents/skills/graphify/SKILL.md",
        "opencode": ".config/opencode/skills/graphify/SKILL.md",
        "kilo": ".config/kilo/skills/graphify/SKILL.md",
        "gemini": ".gemini/skills/graphify/SKILL.md",
        "devin": ".config/devin/skills/graphify/SKILL.md",
        "aider": ".aider/graphify/SKILL.md",
        "copilot": ".copilot/skills/graphify/SKILL.md",
        "vscode": ".copilot/skills/graphify/SKILL.md",
        "claw": ".openclaw/skills/graphify/SKILL.md",
        "droid": ".factory/skills/graphify/SKILL.md",
        "trae": ".trae/skills/graphify/SKILL.md",
        "trae-cn": ".trae-cn/skills/graphify/SKILL.md",
        "hermes": ".hermes/skills/graphify/SKILL.md",
        "kiro": ".kiro/skills/graphify/SKILL.md",
        "pi": ".pi/agent/skills/graphify/SKILL.md",
        "antigravity": ".gemini/config/skills/graphify/SKILL.md",
        "antigravity-windows": ".gemini/config/skills/graphify/SKILL.md",
        "windows": ".claude/skills/graphify/SKILL.md",
        "kimi": ".kimi/skills/graphify/SKILL.md",
        "amp": ".config/agents/skills/graphify/SKILL.md",
    }
    return ExpectedPath("home", mapping[platform_name])


def project_skill(platform_name: str) -> ExpectedPath:
    mapping = {
        "claude": ".claude/skills/graphify/SKILL.md",
        "codex": ".agents/skills/graphify/SKILL.md",
        "opencode": ".opencode/skills/graphify/SKILL.md",
        "kilo": ".config/kilo/skills/graphify/SKILL.md",
        "gemini": ".gemini/skills/graphify/SKILL.md",
        "devin": ".devin/skills/graphify/SKILL.md",
        "aider": ".aider/graphify/SKILL.md",
        "copilot": ".copilot/skills/graphify/SKILL.md",
        "claw": ".openclaw/skills/graphify/SKILL.md",
        "droid": ".factory/skills/graphify/SKILL.md",
        "trae": ".trae/skills/graphify/SKILL.md",
        "trae-cn": ".trae-cn/skills/graphify/SKILL.md",
        "hermes": ".hermes/skills/graphify/SKILL.md",
        "kiro": ".kiro/skills/graphify/SKILL.md",
        "pi": ".pi/agent/skills/graphify/SKILL.md",
        "antigravity": ".agents/skills/graphify/SKILL.md",
        "antigravity-windows": ".agents/skills/graphify/SKILL.md",
        "windows": ".claude/skills/graphify/SKILL.md",
        "kimi": ".kimi/skills/graphify/SKILL.md",
        "amp": ".agents/skills/graphify/SKILL.md",
    }
    return ExpectedPath("project", mapping[platform_name])


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return UNSUPPORTED_SCOPES.get((platform_name, scope))


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    if platform_name in {"copilot", "devin", "pi"}:
        return ("graphify", platform_name, "uninstall")
    return None


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    if scope == "project":
        return ("graphify", "install", "--project", "--platform", platform_name)
    return ("graphify", "install", "--platform", platform_name)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    if scope == "user" and platform_name in DIRECT_USER_EQUIVALENT_PLATFORMS:
        return ("graphify", platform_name, "install")
    if scope == "project" and platform_name in DIRECT_PROJECT_EQUIVALENT_PLATFORMS:
        if platform_name in {"cursor", "kiro"}:
            return ("graphify", platform_name, "install")
        return ("graphify", platform_name, "install", "--project")
    return None


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    if scenario.scope not in {"user", "project"}:
        return None
    generic = generic_install_command(scenario.platform, scenario.scope)
    direct = direct_install_command(scenario.platform, scenario.scope)
    if direct is None:
        return None
    if scenario.install_command == generic:
        return direct
    if scenario.install_command == direct:
        return generic
    return None


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    equivalent = equivalent_install_command(scenario)
    if equivalent is not None:
        return {"status": "runnable", "command": list(equivalent)}
    return {
        "status": "not_applicable",
        "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
    }


def generic_user_skill_scenario(platform_name: str, *, extra_expected: tuple[ExpectedPath, ...] = (), extra_risks: tuple[str, ...] = ()) -> Scenario:
    uninstall = direct_uninstall_command(platform_name)
    notes = list(extra_risks)
    if platform_name in PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL and uninstall is None:
        notes.append("public_cli_lacks_user_skill_uninstall")
    return Scenario(
        platform_name,
        "user",
        ("graphify", "install", "--platform", platform_name),
        uninstall,
        "user_cwd",
        (user_skill(platform_name), *extra_expected),
        risk_notes(*notes, platform_name=platform_name),
    )


def agents_project_scenario(platform_name: str) -> Scenario:
    expected = [project_skill(platform_name), ExpectedPath("project", "AGENTS.md", marker=GRAPHIFY_MARKER)]
    if platform_name == "codex":
        expected.append(ExpectedPath("project", ".codex/hooks.json", marker="graphify"))
    if platform_name == "opencode":
        expected.extend((ExpectedPath("project", ".opencode/plugins/graphify.js"), ExpectedPath("project", ".opencode/opencode.json", marker="graphify")))
    return Scenario(
        platform_name,
        "project",
        ("graphify", "install", "--project", "--platform", platform_name),
        ("graphify", "uninstall", "--project", "--platform", platform_name),
        "project",
        tuple(expected),
        (),
    )


def skill_only_project_scenario(platform_name: str) -> Scenario:
    return Scenario(
        platform_name,
        "project",
        ("graphify", "install", "--project", "--platform", platform_name),
        ("graphify", "uninstall", "--project", "--platform", platform_name),
        "project",
        (project_skill(platform_name),),
        risk_notes(platform_name=platform_name),
    )


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    scopes = ["user", "project"] if scope == "both" else [scope]
    scenarios: list[Scenario] = []
    for one_scope in scopes:
        scenario = make_scenario(platform_name, one_scope)
        if scenario is not None:
            scenarios.append(scenario)
    return scenarios


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    if platform_name not in ALL_PLATFORMS:
        raise RuntimeError(f"unknown sandbox platform: {platform_name}")
    if unsupported_scope_reason(platform_name, scope):
        return None

    if scope == "user":
        if platform_name == "claude":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--platform", "claude"),
                None,
                "user_cwd",
                (user_skill("claude"), ExpectedPath("home", ".claude/CLAUDE.md", marker="# graphify", remove_on_uninstall=False)),
                risk_notes("public_cli_lacks_user_skill_uninstall", platform_name=platform_name),
            )
        if platform_name == "codex":
            return generic_user_skill_scenario("codex")
        if platform_name == "opencode":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--platform", "opencode"),
                None,
                "user_cwd",
                (
                    user_skill("opencode"),
                    ExpectedPath("user_cwd", ".opencode/plugins/graphify.js"),
                    ExpectedPath("user_cwd", ".opencode/opencode.json", marker="graphify"),
                ),
                risk_notes("mixed_scope_project_wiring", "public_cli_lacks_user_skill_uninstall", platform_name=platform_name),
            )
        if platform_name == "kilo":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--platform", "kilo"),
                ("graphify", "kilo", "uninstall"),
                "user_cwd",
                (user_skill("kilo"), ExpectedPath("home", ".config/kilo/command/graphify.md")),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "gemini":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--platform", "gemini"),
                ("graphify", "gemini", "uninstall"),
                "user_cwd",
                (
                    user_skill("gemini"),
                    ExpectedPath("user_cwd", "GEMINI.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("user_cwd", ".gemini/settings.json", marker="graphify"),
                ),
                risk_notes("mixed_scope_project_wiring", platform_name=platform_name),
            )
        if platform_name == "devin":
            return generic_user_skill_scenario("devin")
        if platform_name in {"aider", "amp", "claw", "droid", "trae", "trae-cn", "hermes", "kiro", "windows", "kimi", "antigravity-windows"}:
            return generic_user_skill_scenario(platform_name)
        if platform_name in {"copilot", "pi"}:
            return generic_user_skill_scenario(platform_name)
        if platform_name == "vscode":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "vscode", "install"),
                ("graphify", "vscode", "uninstall"),
                "user_cwd",
                (user_skill("vscode"), ExpectedPath("user_cwd", ".github/copilot-instructions.md", marker=GRAPHIFY_MARKER)),
                risk_notes("mixed_scope_project_wiring", platform_name=platform_name),
            )
        if platform_name == "antigravity":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "antigravity", "install"),
                ("graphify", "antigravity", "uninstall"),
                "user_cwd",
                (
                    user_skill("antigravity"),
                    ExpectedPath("user_cwd", ".agents/rules/graphify.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("user_cwd", ".agents/workflows/graphify.md"),
                ),
                risk_notes("mixed_scope_project_wiring", platform_name=platform_name),
            )

    if scope == "project":
        if platform_name == "claude":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--project", "--platform", "claude"),
                ("graphify", "uninstall", "--project", "--platform", "claude"),
                "project",
                (
                    project_skill("claude"),
                    ExpectedPath("project", ".claude/CLAUDE.md", marker="# graphify"),
                    ExpectedPath("project", "CLAUDE.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("project", ".claude/settings.json", marker="graphify"),
                ),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "codex":
            return agents_project_scenario("codex")
        if platform_name == "opencode":
            return agents_project_scenario("opencode")
        if platform_name == "kilo":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "kilo", "install"),
                ("graphify", "kilo", "uninstall"),
                "project",
                (
                    user_skill("kilo"),
                    ExpectedPath("home", ".config/kilo/command/graphify.md"),
                    ExpectedPath("project", "AGENTS.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("project", ".kilo/plugins/graphify.js"),
                    ExpectedPath("project", ".kilo/kilo.json", marker="graphify"),
                ),
                risk_notes("mixed_scope_global_skill_plus_project_wiring", platform_name=platform_name),
            )
        if platform_name == "gemini":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--project", "--platform", "gemini"),
                ("graphify", "uninstall", "--project", "--platform", "gemini"),
                "project",
                (
                    project_skill("gemini"),
                    ExpectedPath("project", "GEMINI.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("project", ".gemini/settings.json", marker="graphify"),
                ),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "cursor":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "cursor", "install"),
                ("graphify", "cursor", "uninstall"),
                "project",
                (ExpectedPath("project", ".cursor/rules/graphify.mdc"),),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "devin":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--project", "--platform", "devin"),
                ("graphify", "uninstall", "--project", "--platform", "devin"),
                "project",
                (
                    project_skill("devin"),
                    ExpectedPath("project", ".windsurf/rules/graphify.md"),
                ),
                risk_notes(platform_name=platform_name),
            )
        if platform_name in AGENTS_MD_PLATFORMS:
            return agents_project_scenario(platform_name)
        if platform_name in SKILL_ONLY_PROJECT_PLATFORMS:
            return skill_only_project_scenario(platform_name)
        if platform_name == "windows":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "install", "--project", "--platform", "windows"),
                ("graphify", "uninstall", "--project", "--platform", "windows"),
                "project",
                (
                    project_skill("windows"),
                    ExpectedPath("project", ".claude/CLAUDE.md", marker="# graphify"),
                    ExpectedPath("project", "CLAUDE.md", marker=GRAPHIFY_MARKER),
                    ExpectedPath("project", ".claude/settings.json", marker="graphify"),
                ),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "kiro":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "kiro", "install"),
                ("graphify", "kiro", "uninstall"),
                "project",
                (
                    ExpectedPath("project", ".kiro/skills/graphify/SKILL.md"),
                    ExpectedPath("project", ".kiro/steering/graphify.md", marker="graphify:"),
                ),
                risk_notes(platform_name=platform_name),
            )
        if platform_name == "vscode":
            return Scenario(
                platform_name,
                scope,
                ("graphify", "vscode", "install"),
                ("graphify", "vscode", "uninstall"),
                "project",
                (user_skill("vscode"), ExpectedPath("project", ".github/copilot-instructions.md", marker=GRAPHIFY_MARKER)),
                risk_notes("mixed_scope_global_skill_plus_project_wiring", platform_name=platform_name),
            )
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="In-container Graphify install scenario runner.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
    parser.add_argument("--copy-source", choices=("always", "auto"), default="always")
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


def run_capture(command: Iterable[str], *, cwd: Path, env: dict[str, str], artifact_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    command_list = list(command)
    started_at = utc_timestamp()
    start = time.monotonic()
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "command.txt").write_text(" ".join(command_list) + "\n", encoding="utf-8")
        (artifact_dir / "env.json").write_text(json.dumps({k: env.get(k, "") for k in sorted(("HOME", "XDG_CONFIG_HOME", "PATH", "GRAPHIFY_PROJECT"))}, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(command_list, cwd=cwd, env=env, text=True, capture_output=True)
    duration_ms = int((time.monotonic() - start) * 1000)
    if artifact_dir is not None:
        (artifact_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (artifact_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        (artifact_dir / "exit-code.txt").write_text(f"{result.returncode}\n", encoding="utf-8")
        (artifact_dir / "command-result.json").write_text(
            json.dumps(
                {
                    "command": command_list,
                    "cwd": str(cwd),
                    "started_at": started_at,
                    "duration_ms": duration_ms,
                    "exit_code": result.returncode,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "transcript.txt").write_text(
            f"$ {' '.join(command_list)}\n[started-at]\n{started_at}\n[duration-ms]\n{duration_ms}\n\n[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}\n[exit-code]\n{result.returncode}\n",
            encoding="utf-8",
        )
    result.started_at = started_at  # type: ignore[attr-defined]
    result.duration_ms = duration_ms  # type: ignore[attr-defined]
    return result


def list_files(base: Path) -> list[dict[str, object]]:
    if not base.exists():
        return []
    files: list[dict[str, object]] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        try:
            rel = path.relative_to(base).as_posix()
            stat = path.stat()
        except OSError:
            continue
        files.append({"path": rel, "size": stat.st_size})
    return files


def write_file_manifest(path: Path, roots: dict[str, Path]) -> None:
    data = {name: list_files(root) for name, root in roots.items()}
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


def source_manifest(src: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if len(files) < 5000:
            entry = {"path": rel, "size": path.stat().st_size}
            if rel in ("pyproject.toml", "graphify/__main__.py"):
                entry["sha256"] = sha256(path)
            files.append(entry)
    return {"root": str(src), "file_count": sum(1 for _ in src.rglob("*") if _.is_file()), "files_sample": files, "excluded_patterns": list(COPY_EXCLUDES)}


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


def copy_source_tree() -> dict[str, object]:
    if SRC.exists():
        shutil.rmtree(SRC)
    shutil.copytree(REPO_MOUNT, SRC, symlinks=True, ignore=copy_source_ignore)
    return source_manifest(SRC)


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


def dist_to_metadata(dist: importlib.metadata.Distribution, source: Path) -> dict[str, object]:
    direct_url = None
    direct_text = dist.read_text("direct_url.json")
    if direct_text:
        direct_url = json.loads(direct_text)
    source_path = direct_url_source_path(direct_url)
    return {
        "package_name": dist.metadata.get("Name") or PACKAGE_NAME,
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
            if (dist.metadata.get("Name") or "").lower() == package_name.lower():
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
    }


def known_runtime_status_values() -> list[str]:
    return [RISK_GRAPHIFY_VERIFIED, RISK_RUNTIME_VERIFIED, RISK_RUNTIME_UNVERIFIED, RISK_TOOL_UNAVAILABLE]


def target_tool_probe_for_platform(platform_name: str) -> TargetToolProbe:
    try:
        return TOOL_PROBES[platform_name]
    except KeyError as exc:
        raise RuntimeError(f"missing target runtime probe for platform: {platform_name}") from exc


def command_display(command: tuple[str, ...] | None) -> str:
    return "not attempted" if command is None else " ".join(command)


def run_tool_command(command: tuple[str, ...], *, cwd: Path, env: dict[str, str], timeout_seconds: int) -> dict[str, object]:
    started_at = utc_timestamp()
    start = time.monotonic()
    try:
        result = subprocess.run(list(command), cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout_seconds)
        duration_ms = int((time.monotonic() - start) * 1000)
        return {"command": list(command), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "timed_out": False, "started_at": started_at, "duration_ms": duration_ms}
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {"command": list(command), "exit_code": 127, "stdout": "", "stderr": str(exc), "timed_out": False, "started_at": started_at, "duration_ms": duration_ms}
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {"command": list(command), "exit_code": 124, "stdout": stdout, "stderr": stderr, "timed_out": True, "started_at": started_at, "duration_ms": duration_ms}


def no_tool_command_status(probe: TargetToolProbe, artifact_dir: Path, artifact_root: Path) -> dict[str, object]:
    reason = probe.unavailable_reason or "no install or discovery command is defined for this target runtime"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "install.command.txt").write_text(f"not attempted: {reason}\n", encoding="utf-8")
    (artifact_dir / "stdout.txt").write_text("", encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(reason + "\n", encoding="utf-8")
    (artifact_dir / "version.txt").write_text("not verified\n", encoding="utf-8")
    status = {
        "tool": probe.tool,
        "status": RISK_TOOL_UNAVAILABLE,
        "target_tool_runtime_verified": False,
        "credentials_required": probe.credentials_required,
        "docker_headless_expected": probe.docker_headless_expected,
        "command_kind": probe.command_kind,
        "command": None,
        "version_command": None,
        "install_exit_code": None,
        "version_exit_code": None,
        "unavailable_reason": reason,
        "docs_checked": list(probe.docs_checked),
        "evidence_path": artifact_dir.relative_to(artifact_root).as_posix(),
    }
    (artifact_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def run_target_tool_probe(probe: TargetToolProbe, env: dict[str, str], *, artifact_root: Path = OUTPUT) -> dict[str, object]:
    artifact_dir = artifact_root / "tool-install" / probe.tool
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    if probe.command is None:
        return no_tool_command_status(probe, artifact_dir, artifact_root)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "install.command.txt").write_text(command_display(probe.command) + "\n", encoding="utf-8")
    install_result = run_tool_command(probe.command, cwd=Path("/tmp"), env=env, timeout_seconds=probe.timeout_seconds)
    (artifact_dir / "stdout.txt").write_text(str(install_result["stdout"]), encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(str(install_result["stderr"]), encoding="utf-8")

    version_result: dict[str, object] | None = None
    if install_result["exit_code"] == 0 and probe.version_command is not None:
        version_result = run_tool_command(probe.version_command, cwd=Path("/tmp"), env=env, timeout_seconds=probe.timeout_seconds)
        version_text = (
            f"$ {command_display(probe.version_command)}\n\n"
            f"[stdout]\n{version_result['stdout']}\n"
            f"[stderr]\n{version_result['stderr']}\n"
            f"[exit-code]\n{version_result['exit_code']}\n"
        )
    elif install_result["exit_code"] == 0:
        version_text = "version command not defined\n"
    else:
        version_text = "version command not run because discovery/install command failed\n"
    (artifact_dir / "version.txt").write_text(version_text, encoding="utf-8")

    verified = install_result["exit_code"] == 0 and (probe.version_command is None or (version_result is not None and version_result["exit_code"] == 0))
    unavailable_reason = None if verified else probe.unavailable_reason or "target runtime command unavailable or version probe failed in Docker"
    status = {
        "tool": probe.tool,
        "status": RISK_RUNTIME_VERIFIED if verified else RISK_TOOL_UNAVAILABLE,
        "target_tool_runtime_verified": verified,
        "credentials_required": probe.credentials_required,
        "docker_headless_expected": probe.docker_headless_expected,
        "command_kind": probe.command_kind,
        "command": list(probe.command),
        "version_command": None if probe.version_command is None else list(probe.version_command),
        "install_exit_code": install_result["exit_code"],
        "version_exit_code": None if version_result is None else version_result["exit_code"],
        "install_started_at": install_result.get("started_at"),
        "install_duration_ms": install_result.get("duration_ms"),
        "version_started_at": None if version_result is None else version_result.get("started_at"),
        "version_duration_ms": None if version_result is None else version_result.get("duration_ms"),
        "timed_out": bool(install_result.get("timed_out")) or bool(version_result and version_result.get("timed_out")),
        "unavailable_reason": unavailable_reason,
        "docs_checked": list(probe.docs_checked),
        "evidence_path": artifact_dir.relative_to(artifact_root).as_posix(),
    }
    (artifact_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return status


def run_target_tool_probes(platforms: list[str], env: dict[str, str]) -> dict[str, dict[str, object]]:
    statuses: dict[str, dict[str, object]] = {}
    for platform_name in platforms:
        statuses[platform_name] = run_target_tool_probe(target_tool_probe_for_platform(platform_name), env)
    return statuses


def runtime_status_summary(statuses: dict[str, dict[str, object]]) -> dict[str, int]:
    summary = {RISK_RUNTIME_VERIFIED: 0, RISK_TOOL_UNAVAILABLE: 0, RISK_RUNTIME_UNVERIFIED: 0}
    for status in statuses.values():
        value = status.get("status")
        if value in summary:
            summary[str(value)] += 1
        else:
            summary[RISK_RUNTIME_UNVERIFIED] += 1
    return summary


def combined_status(graphify_passed: bool, runtime_status: str | None) -> str:
    if not graphify_passed:
        return "graphify_install_failed"
    if runtime_status == RISK_RUNTIME_VERIFIED:
        return "graphify_install_verified_and_target_runtime_verified"
    if runtime_status == RISK_TOOL_UNAVAILABLE:
        return "graphify_install_verified_but_target_runtime_unavailable"
    return "graphify_install_verified_but_target_runtime_unverified"


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
    if isinstance(command, list):
        command_text = " ".join(str(part) for part in command)
    else:
        command_text = text_snippet(artifact_dir / "command.txt", 1000)
    return {
        "command": command_text,
        "started_at": result.get("started_at"),
        "duration_ms": result.get("duration_ms"),
        "exit_code": result.get("exit_code"),
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


def render_report_md(manifest: dict[str, object]) -> str:
    package = manifest.get("package_install") if isinstance(manifest.get("package_install"), dict) else {}
    preflight_data = manifest.get("preflight") if isinstance(manifest.get("preflight"), dict) else {}
    os_release = manifest.get("os_release") if isinstance(manifest.get("os_release"), dict) else {}
    runtime = manifest.get("target_tool_runtime") if isinstance(manifest.get("target_tool_runtime"), dict) else {}
    runtime_statuses = runtime.get("statuses") if isinstance(runtime.get("statuses"), dict) else {}
    results = manifest.get("results") if isinstance(manifest.get("results"), list) else []
    coverage = manifest.get("platform_coverage") if isinstance(manifest.get("platform_coverage"), list) else []

    lines: list[str] = ["# Graphify Install Sandbox Report", ""]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Graphify file effects: {manifest.get('graphify_file_effect_pass_count', manifest.get('pass_count', 0))} passed, {manifest.get('graphify_file_effect_fail_count', manifest.get('fail_count', 0))} failed.",
            f"- Target runtimes: {manifest.get('target_tool_runtime_verified_scenario_count', 0)} verified, {manifest.get('target_tool_runtime_unavailable_scenario_count', 0)} unavailable, {manifest.get('target_tool_runtime_unverified_scenario_count', 0)} unverified.",
            *([f"- Target runtime probes skipped: {md_cell(runtime.get('skip_reason') or 'Graphify checks failed')}."] if runtime.get("skipped") else []),
            f"- Scenario count: {manifest.get('scenario_count', len(results))}.",
            f"- Artifacts: {md_code('manifest.json')}, {md_code('preflight.json')}, {md_code('package-install/')}, {md_code('tool-install/')}, {md_code('scenarios/')}.",
            "",
            "## Environment",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| OS | {md_cell(os_release.get('PRETTY_NAME') or os_release.get('NAME'))} |",
            f"| Architecture | {md_cell(manifest.get('architecture'))} |",
            f"| Python | {md_cell(manifest.get('python_version'))} |",
            f"| Graphify version | {md_cell(manifest.get('graphify_version'))} |",
            f"| Install mode | {md_cell(package.get('install_mode'))} |",
            f"| Package name | {md_cell(package.get('package_name'))} |",
            f"| Install location | {md_cell(package.get('location'))} |",
            f"| Installed from copied source | {md_cell(package.get('installed_from_copied_source'))} |",
            f"| Source root | {md_cell((manifest.get('source_snapshot') or {}).get('root') if isinstance(manifest.get('source_snapshot'), dict) else '')} |",
            f"| Sandbox project | {md_cell(preflight_data.get('project'))} |",
            "",
            "## Status Vocabulary",
            "",
        ]
    )
    for status in manifest.get("risk_status_values", known_runtime_status_values()):
        lines.append(f"- {md_code(status)}")
    lines.extend(["", "## Scenario Status", "", "| Platform | Scope | Scenario | Graphify Install | Target Runtime | Overall Status | Duration | Transcript |", "|---|---|---|---|---|---|---:|---|"])
    for item in results:
        if not isinstance(item, dict):
            continue
        graphify_status = RISK_GRAPHIFY_VERIFIED if item.get("graphify_file_effects_passed", item.get("passed")) else "graphify_install_failed"
        command_artifact = item.get("command_artifact") if isinstance(item.get("command_artifact"), dict) else {}
        duration = item.get("duration_ms") or command_artifact.get("duration_ms")
        transcript = command_artifact.get("transcript_path") or item.get("transcript_path") or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(item.get("platform")),
                    md_cell(item.get("scope")),
                    md_cell(item.get("id")),
                    md_cell(graphify_status),
                    md_cell(item.get("target_tool_runtime_status", RISK_RUNTIME_UNVERIFIED)),
                    md_cell(status_label(item)),
                    md_cell(f"{duration} ms" if duration is not None else ""),
                    md_cell(transcript),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Platform Coverage", "", "| Platform | Scope | Coverage | Install Command | Runtime Status | Runtime Evidence |", "|---|---|---|---|---|---|"])
    for record in coverage:
        if not isinstance(record, dict):
            continue
        probe = record.get("target_tool_runtime_probe") if isinstance(record.get("target_tool_runtime_probe"), dict) else {}
        command = record.get("install_command")
        command_text = " ".join(str(part) for part in command) if isinstance(command, list) else record.get("reason", "")
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(record.get("platform")),
                    md_cell(record.get("scope")),
                    md_cell(record.get("status")),
                    md_cell(command_text),
                    md_cell(probe.get("status")),
                    md_cell(probe.get("evidence_path")),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Runtime Risks", ""])
    risk_rows: list[str] = []
    for platform_name, status in runtime_statuses.items():
        if not isinstance(status, dict):
            continue
        runtime_status = status.get("status")
        if runtime_status == RISK_RUNTIME_VERIFIED:
            continue
        reason = status.get("unavailable_reason") or "runtime was not verified"
        risk_rows.append(f"- {md_code(platform_name)}: {md_code(runtime_status)}; evidence {md_code(status.get('evidence_path'))}; {reason}")
    lines.extend(risk_rows or ["- None."])

    windows_validation = manifest.get("windows_validation") if isinstance(manifest.get("windows_validation"), dict) else default_windows_validation_status()
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
    notes = windows_validation.get("notes") if isinstance(windows_validation.get("notes"), list) else []
    targets = windows_validation.get("targets") if isinstance(windows_validation.get("targets"), list) else []
    for note in notes:
        lines.append(f"- {md_cell(note)}")
    if targets:
        lines.append(f"- Targets: {md_cell(', '.join(str(target) for target in targets))}")

    failures = [item for item in results if isinstance(item, dict) and item.get("passed") is not True]
    lines.extend(["", "## Failures", ""])
    if failures:
        for item in failures:
            command_artifact = item.get("command_artifact") if isinstance(item.get("command_artifact"), dict) else {}
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

    lines.extend(["", "## Command Transcripts", "", "| Scenario | Command | Started | Duration | Exit | Transcript |", "|---|---|---|---:|---:|---|"])
    for item in results:
        if not isinstance(item, dict):
            continue
        command_artifact = item.get("command_artifact") if isinstance(item.get("command_artifact"), dict) else {}
        if not command_artifact:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(item.get("id")),
                    md_cell(command_artifact.get("command")),
                    md_cell(command_artifact.get("started_at")),
                    md_cell(command_artifact.get("duration_ms")),
                    md_cell(command_artifact.get("exit_code")),
                    md_cell(command_artifact.get("transcript_path")),
                ]
            )
            + " |"
        )

    return "\n".join(lines).rstrip() + "\n"


def write_report_md(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(render_report_md(manifest), encoding="utf-8")


def default_windows_validation_status() -> dict[str, object]:
    return {
        "status": "risk",
        "evidence_path": None,
        "strategy": "separate Windows host/CI validation path; Linux Docker only simulates file layout for Windows platforms",
        "targets": list(WINDOWS_VALIDATION_TARGETS),
        "notes": [
            "Linux sandbox results for windows and antigravity-windows are Graphify-owned file-layout checks only.",
            "No local Windows validation path is configured; real Windows path, payload, and cleanup behavior remain residual risk.",
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
    result = run_capture(install_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir)
    if result.returncode != 0:
        raise RuntimeError("pip install failed; see package-install artifacts")

    metadata = read_installed_package_metadata(PACKAGE_NAME, SRC)
    version_command = ("graphify", "--version")
    probe_result = run_capture(version_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir / "graphify-version")
    probe = command_probe_summary(probe_result, version_command)
    metadata["version"] = metadata.get("version") or version_from_probe(probe)
    metadata["install_mode"] = INSTALL_MODE
    metadata["install_command"] = list(install_command)
    metadata["command_probe"] = probe
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


def assert_expected_files(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = expected_path(entry)
        exists = path.exists()
        ok = exists
        detail = "exists" if exists else "missing"
        if exists and entry.marker:
            text = path.read_text(encoding="utf-8", errors="replace")
            marker_count = text.count(entry.marker)
            if path.suffix == ".json":
                ok = marker_count >= 1
                detail = f"marker_present={marker_count >= 1}; marker_count={marker_count}"
            else:
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
        checks.append({"path": str(path), "root": entry.root, "relative": entry.relative, "ok": ok, "detail": detail})
        checks.extend(assert_installed_skill_sidecar(scenario, entry))
    return checks


def assert_uninstalled(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = expected_path(entry)
        if not entry.remove_on_uninstall:
            continue
        if entry.marker and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            ok = entry.marker not in text and STALE_GRAPHIFY_SENTINEL not in text
            if USER_SENTINEL in text:
                detail = "graphify_removed; user_content_preserved"
            else:
                detail = "graphify_removed"
        else:
            ok = not path.exists()
            detail = "removed" if ok else "still_exists"
        checks.append({"path": str(path), "root": entry.root, "relative": entry.relative, "ok": ok, "detail": detail})
    return checks


def assert_scope_boundaries(scenario: Scenario) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        allowed = True
        if scenario.scope == "user" and entry.root not in ("home",):
            allowed = "mixed_scope_project_wiring" in scenario.risk_notes
        if scenario.scope == "project" and entry.root not in ("project",):
            allowed = "mixed_scope_global_skill_plus_project_wiring" in scenario.risk_notes
        checks.append({"path": str(expected_path(entry)), "ok": allowed, "detail": "allowed_root" if allowed else "unexpected_root"})
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
        checks.append({"path": key, "ok": stable, "detail": "unchanged_after_repeat_install" if stable else "changed_after_repeat_install"})
    return checks


def should_exclude_generated_path(relative: Path) -> bool:
    return any(part in GENERATED_COPY_EXCLUDES for part in relative.parts)


def is_relevant_generated_file(scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
    rel = relative.as_posix()
    expected = {(entry.root, entry.relative) for entry in scenario.expected}
    if (root_name, rel) in expected:
        return True
    for entry in scenario.expected:
        if root_name != entry.root or not is_skill_expected(entry):
            continue
        skill_rel_dir = skill_relative_dir(entry)
        if relative == skill_rel_dir / ".graphify_version":
            return True
        try:
            relative.relative_to(skill_rel_dir / "references")
            return True
        except ValueError:
            pass
        try:
            relative.relative_to(skill_rel_dir / "references.tmp")
            return True
        except ValueError:
            pass
    if relative.name == ".graphify_version" and any(
        root_name == entry.root and relative.parent.as_posix() == Path(entry.relative).parent.as_posix()
        for entry in scenario.expected
    ):
        return True
    if "graphify" in rel.lower():
        return True
    if path.stat().st_size > 1024 * 1024:
        return False
    text_suffixes = {".json", ".js", ".md", ".mdc", ".txt", ""}
    if path.suffix not in text_suffixes:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "graphify" in text.lower() or USER_SENTINEL in text


def copy_generated_files(scenario: Scenario, artifact_dir: Path) -> None:
    out = artifact_dir / "generated-files"
    if out.exists():
        shutil.rmtree(out)
    for root_name, root in ROOTS.items():
        if not root.exists():
            continue
        target = out / root_name
        for path in root.rglob("*"):
            if path.is_file():
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
    write_file_manifest(artifact_dir / "before-files.json", ROOTS)
    cwd = root_path(scenario.cwd_root)
    result = run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir)
    checks = assert_expected_files(scenario) + assert_scope_boundaries(scenario)
    state = scenario_file_state(scenario)
    write_file_manifest(artifact_dir / "after-files.json", ROOTS)
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


def risk_report(scenario: Scenario, passed: bool, target_tool_status: dict[str, object] | None = None) -> dict[str, object]:
    runtime_status = RISK_RUNTIME_UNVERIFIED
    runtime_verified = False
    runtime_notes: list[str] = []
    if target_tool_status is not None:
        raw_status = target_tool_status.get("status")
        if raw_status in {RISK_RUNTIME_VERIFIED, RISK_TOOL_UNAVAILABLE, RISK_RUNTIME_UNVERIFIED}:
            runtime_status = str(raw_status)
        runtime_verified = runtime_status == RISK_RUNTIME_VERIFIED
        evidence_path = target_tool_status.get("evidence_path")
        if isinstance(evidence_path, str):
            runtime_notes.append(f"target_runtime_evidence={evidence_path}")
        unavailable_reason = target_tool_status.get("unavailable_reason")
        if isinstance(unavailable_reason, str) and unavailable_reason:
            runtime_notes.append(unavailable_reason)
    runtime_risk = RISK_RUNTIME_VERIFIED if runtime_verified else runtime_status
    statuses = [RISK_GRAPHIFY_VERIFIED if passed else "graphify_install_failed", runtime_risk]
    return {
        "statuses": statuses,
        "target_tool_runtime_verified": runtime_verified,
        "tool_runtime_status": runtime_status,
        "target_tool_runtime": target_tool_status,
        "notes": list(scenario.risk_notes) + runtime_notes,
        "known_status_values": known_runtime_status_values(),
    }


def run_scenario(scenario: Scenario, env: dict[str, str], target_tool_statuses: dict[str, dict[str, object]]) -> dict[str, object]:
    scenario_started_at = utc_timestamp()
    scenario_start = time.monotonic()
    reset_sandbox_dirs()
    artifact_dir = OUTPUT / "scenarios" / scenario_id(scenario.platform, scenario.scope)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    seed_user_owned_content(scenario)
    write_file_manifest(artifact_dir / "before-files.json", ROOTS)

    cwd = root_path(scenario.cwd_root)
    install_1 = run_capture(scenario.install_command, cwd=cwd, env=env, artifact_dir=artifact_dir)
    state_after_install = scenario_file_state(scenario)
    install_checks = assert_expected_files(scenario)
    scope_checks = assert_scope_boundaries(scenario)
    idempotency_checks: list[dict[str, object]] = []
    uninstall_checks: list[dict[str, object]] = []
    equivalence_checks: list[dict[str, object]] = []
    stale_sidecar_repair_seeded: list[dict[str, object]] = []
    stale_sidecar_repair_checks: list[dict[str, object]] = []
    install_2 = None
    stale_sidecar_repair_result = None
    uninstall_result = None
    state_after_repeat: dict[str, dict[str, object]] = {}

    if install_1.returncode == 0:
        install_2 = run_capture(scenario.install_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "repeat-install")
        state_after_repeat = scenario_file_state(scenario)
        idempotency_checks = assert_idempotent_state(state_after_install, state_after_repeat)
        if install_2.returncode == 0:
            stale_sidecar_repair_seeded = seed_stale_skill_sidecars(scenario)
            if stale_sidecar_repair_seeded:
                stale_sidecar_repair_result = run_capture(scenario.install_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "stale-sidecar-repair")
                if stale_sidecar_repair_result.returncode == 0:
                    stale_sidecar_repair_checks = assert_installed_skill_sidecars(scenario)
        if scenario.uninstall_command:
            uninstall_result = run_capture(scenario.uninstall_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "uninstall")
            uninstall_checks = assert_uninstalled(scenario)
        equivalence_checks = run_equivalence_check(scenario, env, artifact_dir)
    write_file_manifest(artifact_dir / "after-files.json", ROOTS)
    copy_generated_files(scenario, artifact_dir)

    command_ok = (
        install_1.returncode == 0
        and install_2 is not None
        and install_2.returncode == 0
        and (stale_sidecar_repair_result is None or stale_sidecar_repair_result.returncode == 0)
        and (uninstall_result is None or uninstall_result.returncode == 0)
    )
    checks = install_checks + scope_checks + idempotency_checks + stale_sidecar_repair_checks + uninstall_checks + equivalence_checks
    passed = command_ok and all(check["ok"] for check in checks)
    target_tool_status = target_tool_statuses.get(scenario.platform)
    assertions = {
        "scenario": {"platform": scenario.platform, "scope": scenario.scope, "id": scenario_id(scenario.platform, scenario.scope)},
        "passed": passed,
        "install_exit_code": install_1.returncode,
        "repeat_install_exit_code": None if install_2 is None else install_2.returncode,
        "stale_sidecar_repair_exit_code": None if stale_sidecar_repair_result is None else stale_sidecar_repair_result.returncode,
        "stale_sidecar_repair_seeded": stale_sidecar_repair_seeded,
        "stale_sidecar_repair_checks": stale_sidecar_repair_checks,
        "uninstall_exit_code": None if uninstall_result is None else uninstall_result.returncode,
        "target_tool_runtime_status": target_tool_status,
        "state_after_install": state_after_install,
        "state_after_repeat_install": state_after_repeat,
        "generic_direct_equivalence": equivalence_status(scenario),
        "checks": checks,
    }
    risks = risk_report(scenario, passed, target_tool_status)
    (artifact_dir / "assertions.json").write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "risk.json").write_text(json.dumps(risks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    duration_ms = int((time.monotonic() - scenario_start) * 1000)
    return {
        "id": scenario_id(scenario.platform, scenario.scope),
        "platform": scenario.platform,
        "scope": scenario.scope,
        "started_at": scenario_started_at,
        "duration_ms": duration_ms,
        "reproduction_command": " ".join(scenario.install_command),
        "command_artifact": command_artifact_summary(artifact_dir),
        "overall_status": combined_status(passed, str(risks["tool_runtime_status"])),
        "graphify_file_effects_passed": passed,
        "passed": passed,
        "risks": risks["statuses"],
        "target_tool_runtime_status": risks["tool_runtime_status"],
        "target_tool_runtime_verified": risks["target_tool_runtime_verified"],
    }


def run_universal_uninstall_scenario(scope: str, scenarios: list[Scenario], env: dict[str, str]) -> dict[str, object]:
    scenario_started_at = utc_timestamp()
    scenario_start = time.monotonic()
    reset_sandbox_dirs()
    scenario_name = f"universal-uninstall-{scope}"
    artifact_dir = OUTPUT / "scenarios" / scenario_name
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for scenario in scenarios:
        seed_user_owned_content(scenario)
    write_file_manifest(artifact_dir / "before-files.json", ROOTS)

    install_results = []
    for scenario in scenarios:
        install_dir = artifact_dir / "installs" / scenario_id(scenario.platform, scenario.scope)
        result = run_capture(scenario.install_command, cwd=root_path(scenario.cwd_root), env=env, artifact_dir=install_dir)
        install_results.append({"scenario_id": scenario_id(scenario.platform, scenario.scope), "command": list(scenario.install_command), "exit_code": result.returncode})

    if scope == "project":
        uninstall_command = ("graphify", "uninstall", "--project")
        cwd = PROJECT
    else:
        uninstall_command = ("graphify", "uninstall")
        cwd = USER_CWD
    uninstall_result = run_capture(uninstall_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "uninstall")
    checks = [check for scenario in scenarios for check in assert_uninstalled(scenario)]
    write_file_manifest(artifact_dir / "after-files.json", ROOTS)
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
        "statuses": [RISK_GRAPHIFY_VERIFIED if passed else "graphify_install_failed", RISK_RUNTIME_UNVERIFIED],
        "target_tool_runtime_verified": False,
        "tool_runtime_status": RISK_RUNTIME_UNVERIFIED,
        "notes": ["universal uninstall covers Graphify-owned file effects after multiple installs"],
        "known_status_values": known_runtime_status_values(),
    }
    (artifact_dir / "assertions.json").write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "risk.json").write_text(json.dumps(risks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "id": scenario_name,
        "platform": "multiple",
        "scope": scope,
        "started_at": scenario_started_at,
        "duration_ms": int((time.monotonic() - scenario_start) * 1000),
        "reproduction_command": " ".join(uninstall_command),
        "command_artifact": command_artifact_summary(artifact_dir / "uninstall"),
        "graphify_file_effects_passed": passed,
        "overall_status": combined_status(passed, RISK_RUNTIME_UNVERIFIED),
        "passed": passed,
        "risks": risks["statuses"],
        "target_tool_runtime_status": RISK_RUNTIME_UNVERIFIED,
        "target_tool_runtime_verified": False,
    }


def run_purge_scenario(env: dict[str, str]) -> dict[str, object]:
    scenario_started_at = utc_timestamp()
    scenario_start = time.monotonic()
    reset_sandbox_dirs()
    scenario_name = "purge-disposable-graphify-out"
    artifact_dir = OUTPUT / "scenarios" / scenario_name
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    graphify_out = PROJECT / "graphify-out"
    graphify_out.mkdir(parents=True, exist_ok=True)
    (graphify_out / "graph.json").write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    write_file_manifest(artifact_dir / "before-files.json", ROOTS)
    command = ("graphify", "uninstall", "--purge")
    result = run_capture(command, cwd=PROJECT, env=env, artifact_dir=artifact_dir / "uninstall-purge")
    purged = not graphify_out.exists()
    write_file_manifest(artifact_dir / "after-files.json", ROOTS)
    checks = [{"path": str(graphify_out), "ok": purged, "detail": "purged" if purged else "still_exists"}]
    passed = result.returncode == 0 and purged
    assertions = {
        "scenario": {"id": scenario_name, "scope": "project", "platform": "purge"},
        "passed": passed,
        "uninstall_exit_code": result.returncode,
        "checks": checks,
    }
    risks = {
        "statuses": [RISK_GRAPHIFY_VERIFIED if passed else "graphify_install_failed", RISK_RUNTIME_UNVERIFIED],
        "target_tool_runtime_verified": False,
        "tool_runtime_status": RISK_RUNTIME_UNVERIFIED,
        "notes": ["purge verified only against disposable sandbox graphify-out state"],
        "known_status_values": known_runtime_status_values(),
    }
    (artifact_dir / "assertions.json").write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "risk.json").write_text(json.dumps(risks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "id": scenario_name,
        "platform": "purge",
        "scope": "project",
        "started_at": scenario_started_at,
        "duration_ms": int((time.monotonic() - scenario_start) * 1000),
        "reproduction_command": " ".join(command),
        "command_artifact": command_artifact_summary(artifact_dir / "uninstall-purge"),
        "graphify_file_effects_passed": passed,
        "overall_status": combined_status(passed, RISK_RUNTIME_UNVERIFIED),
        "passed": passed,
        "risks": risks["statuses"],
        "target_tool_runtime_status": RISK_RUNTIME_UNVERIFIED,
        "target_tool_runtime_verified": False,
    }


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
    requested = set(platforms)
    groups: list[tuple[str, list[Scenario]]] = []
    if scope in {"user", "both"}:
        scenarios = [make_scenario(platform_name, "user") for platform_name in UNIVERSAL_USER_PLATFORMS if platform_name in requested]
        runnable = [scenario for scenario in scenarios if scenario is not None]
        if len(runnable) >= 2:
            groups.append(("user", runnable))
    if scope in {"project", "both"}:
        scenarios = [make_scenario(platform_name, "project") for platform_name in UNIVERSAL_PROJECT_PLATFORMS if platform_name in requested]
        runnable = [scenario for scenario in scenarios if scenario is not None]
        if len(runnable) >= 2:
            groups.append(("project", runnable))
    return groups


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], target_tool_statuses: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for scenario in [scenario for platform_name in platforms for scenario in platform_scenarios(platform_name, scope)]:
        result = run_scenario(scenario, env, target_tool_statuses)
        results.append(result)
        if result.get("passed") is not True:
            return results
    for universal_scope, scenarios in universal_uninstall_scenarios(platforms, scope):
        result = run_universal_uninstall_scenario(universal_scope, scenarios, env)
        results.append(result)
        if result.get("passed") is not True:
            return results
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


def target_tool_probe_record(platform_name: str, target_tool_statuses: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
    probe = target_tool_probe_for_platform(platform_name)
    status = None if target_tool_statuses is None else target_tool_statuses.get(platform_name)
    return {
        "tool": probe.tool,
        "command_kind": probe.command_kind,
        "command": None if probe.command is None else list(probe.command),
        "version_command": None if probe.version_command is None else list(probe.version_command),
        "credentials_required": probe.credentials_required,
        "docker_headless_expected": probe.docker_headless_expected,
        "unavailable_reason": probe.unavailable_reason,
        "docs_checked": list(probe.docs_checked),
        "status": None if status is None else status.get("status"),
        "evidence_path": None if status is None else status.get("evidence_path"),
    }


def scenario_runtime_status(result: dict[str, object], target_tool_statuses: dict[str, dict[str, object]]) -> tuple[str, bool]:
    platform_name = result.get("platform")
    if not isinstance(platform_name, str):
        return RISK_RUNTIME_UNVERIFIED, False
    target_tool_status = target_tool_statuses.get(platform_name)
    if target_tool_status is None:
        return RISK_RUNTIME_UNVERIFIED, False
    raw_status = target_tool_status.get("status")
    if raw_status not in {RISK_RUNTIME_VERIFIED, RISK_TOOL_UNAVAILABLE, RISK_RUNTIME_UNVERIFIED}:
        return RISK_RUNTIME_UNVERIFIED, False
    runtime_status = str(raw_status)
    return runtime_status, runtime_status == RISK_RUNTIME_VERIFIED


def attach_target_tool_statuses(results: list[dict[str, object]], target_tool_statuses: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    updated_results: list[dict[str, object]] = []
    for result in results:
        updated = dict(result)
        runtime_status, runtime_verified = scenario_runtime_status(updated, target_tool_statuses)
        graphify_passed = bool(updated.get("graphify_file_effects_passed", updated.get("passed") is True))
        runtime_risk = RISK_RUNTIME_VERIFIED if runtime_verified else runtime_status
        updated["risks"] = [RISK_GRAPHIFY_VERIFIED if graphify_passed else "graphify_install_failed", runtime_risk]
        updated["target_tool_runtime_status"] = runtime_status
        updated["target_tool_runtime_verified"] = runtime_verified
        updated["overall_status"] = combined_status(graphify_passed, runtime_status)
        updated_results.append(updated)
    return updated_results


def platform_coverage_records(platforms: list[str], scope: str, target_tool_statuses: dict[str, dict[str, object]] | None = None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for platform_name in platforms:
        target_probe = target_tool_probe_record(platform_name, target_tool_statuses)
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
                        "target_tool_runtime_probe": target_probe,
                    }
                )
            else:
                records.append(
                    {
                        "platform": platform_name,
                        "scope": one_scope,
                        "status": "unsupported",
                        "reason": reason or "no sandbox scenario is defined for this platform/scope",
                        "target_tool_runtime_probe": target_probe,
                    }
                )
    return records


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = sandbox_env()
    preflight_data = preflight()
    src_data = copy_source_tree()
    package_data = install_graphify(env)
    platforms = selected_platforms(args)
    scenarios = selected_scenarios(args)

    results = run_matrix_scenarios(platforms, args.scope, env, {})
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed

    target_tool_statuses: dict[str, dict[str, object]] = {}
    target_tool_runtime_skipped = failed > 0
    target_tool_runtime_skip_reason = None
    if target_tool_runtime_skipped:
        target_tool_runtime_skip_reason = "Graphify install/file-effect scenario failed; target runtime probes skipped."
    else:
        target_tool_statuses = run_target_tool_probes(platforms, env)
        results = attach_target_tool_statuses(results, target_tool_statuses)

    coverage = platform_coverage_records(platforms, args.scope, target_tool_statuses)
    target_results = [result for result in results if result.get("platform") in platforms]
    runtime_verified = sum(1 for result in target_results if result.get("target_tool_runtime_verified") is True)
    runtime_unavailable = sum(1 for result in target_results if result.get("target_tool_runtime_status") == RISK_TOOL_UNAVAILABLE)
    runtime_unverified = sum(1 for result in target_results if result.get("target_tool_runtime_status") == RISK_RUNTIME_UNVERIFIED)
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
        "target_tool_runtime": {
            "statuses": target_tool_statuses,
            "summary": runtime_status_summary(target_tool_statuses),
            "skipped": target_tool_runtime_skipped,
            "skip_reason": target_tool_runtime_skip_reason,
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
        "target_tool_runtime_verified_scenario_count": runtime_verified,
        "target_tool_runtime_unavailable_scenario_count": runtime_unavailable,
        "target_tool_runtime_unverified_scenario_count": runtime_unverified,
        "pass_count": passed,
        "fail_count": failed,
        "results": results,
        "risk_status_values": known_runtime_status_values(),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report_md(OUTPUT / "report.md", manifest)
    print(json.dumps({"passed": passed, "failed": failed, "output": str(OUTPUT), "report": str(OUTPUT / "report.md"), "target_tool_runtime_skipped": target_tool_runtime_skipped}, indent=2), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
