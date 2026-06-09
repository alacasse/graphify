from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


GRAPHIFY_MARKER = "## graphify"
PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE = "public_cli_lacks_user_skill_uninstall"
MIXED_SCOPE_PROJECT_WIRING_NOTE = "mixed_scope_project_wiring"
MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE = "mixed_scope_global_skill_plus_project_wiring"
SIMULATED_LINUX_LAYOUT_NOTE = "simulated_linux_file_layout_only"


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
class ScopeSpec:
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[ExpectedPath, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    equivalent_install_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    user_skill: str | None = None
    project_skill: str | None = None
    scopes: dict[str, ScopeSpec] = field(default_factory=dict)
    unsupported_scopes: dict[str, str] = field(default_factory=dict)
    uses_packaged_references: bool = True
    reference_bundles: tuple[str, ...] = ()
    simulated_linux_layout: bool = False
    universal_uninstall_scopes: tuple[str, ...] = ()


def _dedupe_notes(*notes: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(note for note in notes if note))


def _generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    if scope == "project":
        return ("graphify", "install", "--project", "--platform", platform_name)
    return ("graphify", "install", "--platform", platform_name)


def _generic_uninstall_command(platform_name: str, scope: str) -> tuple[str, ...]:
    if scope == "project":
        return ("graphify", "uninstall", "--project", "--platform", platform_name)
    return ("graphify", "uninstall", "--platform", platform_name)


def _direct_project_install(platform_name: str) -> tuple[str, ...]:
    return ("graphify", platform_name, "install", "--project")


def _skill(root: str, relative: str) -> ExpectedPath:
    return ExpectedPath(root, relative)


def _section(root: str, relative: str, marker: str = GRAPHIFY_MARKER, *, remove_on_uninstall: bool = True) -> ExpectedPath:
    return ExpectedPath(root, relative, marker=marker, remove_on_uninstall=remove_on_uninstall)


def _json_marker(root: str, relative: str) -> ExpectedPath:
    return ExpectedPath(root, relative, marker="graphify")


def _scenario(
    platform_name: str,
    scope: str,
    expected: tuple[ExpectedPath, ...],
    *,
    install_command: tuple[str, ...] | None = None,
    uninstall_command: tuple[str, ...] | None | Literal["generic"] = "generic",
    cwd_root: str | None = None,
    risk_notes: tuple[str, ...] = (),
    equivalent_install_command: tuple[str, ...] | None = None,
) -> ScopeSpec:
    if uninstall_command == "generic":
        uninstall = _generic_uninstall_command(platform_name, scope)
    else:
        uninstall = uninstall_command
    return ScopeSpec(
        install_command=install_command or _generic_install_command(platform_name, scope),
        uninstall_command=uninstall,
        cwd_root=cwd_root or ("project" if scope == "project" else "user_cwd"),
        expected=expected,
        risk_notes=risk_notes,
        equivalent_install_command=equivalent_install_command,
    )


def _generic_user_scope(platform_name: str, skill_relative: str, *, extra_expected: tuple[ExpectedPath, ...] = (), notes: tuple[str, ...] = ()) -> ScopeSpec:
    return _scenario(
        platform_name,
        "user",
        (_skill("home", skill_relative), *extra_expected),
        uninstall_command=None,
        risk_notes=notes,
    )


def _agents_project_scope(platform_name: str, skill_relative: str, *, extra_expected: tuple[ExpectedPath, ...] = (), equivalent: bool = True) -> ScopeSpec:
    return _scenario(
        platform_name,
        "project",
        (_skill("project", skill_relative), _section("project", "AGENTS.md"), *extra_expected),
        equivalent_install_command=_direct_project_install(platform_name) if equivalent else None,
    )


def _skill_only_project_scope(platform_name: str, skill_relative: str, *, notes: tuple[str, ...] = (), equivalent: bool = False) -> ScopeSpec:
    return _scenario(
        platform_name,
        "project",
        (_skill("project", skill_relative),),
        risk_notes=notes,
        equivalent_install_command=_direct_project_install(platform_name) if equivalent else None,
    )


# Temporary sandbox-owned source of platform file effects. The app installer
# refactor should eventually expose an app-owned install plan that this adapter
# can consume instead of maintaining sandbox-local tool specifics.
SANDBOX_PLATFORM_SPECS: dict[str, PlatformSpec] = {
    "claude": PlatformSpec(
        name="claude",
        user_skill=".claude/skills/graphify/SKILL.md",
        project_skill=".claude/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope(
                "claude",
                ".claude/skills/graphify/SKILL.md",
                extra_expected=(_section("home", ".claude/CLAUDE.md", "# graphify", remove_on_uninstall=False),),
                notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,),
            ),
            "project": _scenario(
                "claude",
                "project",
                (
                    _skill("project", ".claude/skills/graphify/SKILL.md"),
                    _section("project", ".claude/CLAUDE.md", "# graphify"),
                    _section("project", "CLAUDE.md"),
                    _json_marker("project", ".claude/settings.json"),
                ),
                equivalent_install_command=_direct_project_install("claude"),
            ),
        },
        universal_uninstall_scopes=("project",),
    ),
    "codex": PlatformSpec(
        name="codex",
        user_skill=".codex/skills/graphify/SKILL.md",
        project_skill=".codex/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("codex", ".codex/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("codex", ".codex/skills/graphify/SKILL.md", extra_expected=(_json_marker("project", ".codex/hooks.json"),)),
        },
        universal_uninstall_scopes=("project",),
    ),
    "codebuddy": PlatformSpec(
        name="codebuddy",
        user_skill=".codebuddy/skills/graphify/SKILL.md",
        project_skill=".codebuddy/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "codebuddy",
                "user",
                (
                    _skill("home", ".codebuddy/skills/graphify/SKILL.md"),
                    _section("home", ".codebuddy/CODEBUDDY.md"),
                    _json_marker("home", ".codebuddy/settings.json"),
                ),
                uninstall_command=("graphify", "uninstall"),
            ),
            "project": _scenario(
                "codebuddy",
                "project",
                (
                    _skill("project", ".codebuddy/skills/graphify/SKILL.md"),
                    _section("project", "CODEBUDDY.md"),
                    _json_marker("project", ".codebuddy/settings.json"),
                ),
                equivalent_install_command=("graphify", "codebuddy", "install"),
            ),
        },
        universal_uninstall_scopes=("user", "project"),
    ),
    "opencode": PlatformSpec(
        name="opencode",
        user_skill=".config/opencode/skills/graphify/SKILL.md",
        project_skill=".opencode/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "opencode",
                "user",
                (
                    _skill("home", ".config/opencode/skills/graphify/SKILL.md"),
                    ExpectedPath("user_cwd", ".opencode/plugins/graphify.js"),
                    _json_marker("user_cwd", ".opencode/opencode.json"),
                ),
                uninstall_command=None,
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE, PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE),
            ),
            "project": _agents_project_scope(
                "opencode",
                ".opencode/skills/graphify/SKILL.md",
                extra_expected=(ExpectedPath("project", ".opencode/plugins/graphify.js"), _json_marker("project", ".opencode/opencode.json")),
            ),
        },
    ),
    "kilo": PlatformSpec(
        name="kilo",
        user_skill=".config/kilo/skills/graphify/SKILL.md",
        project_skill=".config/kilo/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "kilo",
                "user",
                (_skill("home", ".config/kilo/skills/graphify/SKILL.md"), ExpectedPath("home", ".config/kilo/command/graphify.md")),
                uninstall_command=("graphify", "kilo", "uninstall"),
            ),
            "project": _scenario(
                "kilo",
                "project",
                (
                    _skill("home", ".config/kilo/skills/graphify/SKILL.md"),
                    ExpectedPath("home", ".config/kilo/command/graphify.md"),
                    _section("project", "AGENTS.md"),
                    ExpectedPath("project", ".kilo/plugins/graphify.js"),
                    _json_marker("project", ".kilo/kilo.json"),
                ),
                install_command=("graphify", "kilo", "install"),
                uninstall_command=("graphify", "kilo", "uninstall"),
                risk_notes=(MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,),
            ),
        },
    ),
    "gemini": PlatformSpec(
        name="gemini",
        user_skill=".gemini/skills/graphify/SKILL.md",
        project_skill=".gemini/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "gemini",
                "user",
                (
                    _skill("home", ".gemini/skills/graphify/SKILL.md"),
                    _section("user_cwd", "GEMINI.md"),
                    _json_marker("user_cwd", ".gemini/settings.json"),
                ),
                uninstall_command=("graphify", "gemini", "uninstall"),
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE,),
                equivalent_install_command=("graphify", "gemini", "install"),
            ),
            "project": _scenario(
                "gemini",
                "project",
                (_skill("project", ".gemini/skills/graphify/SKILL.md"), _section("project", "GEMINI.md"), _json_marker("project", ".gemini/settings.json")),
                equivalent_install_command=_direct_project_install("gemini"),
            ),
        },
        universal_uninstall_scopes=("user", "project"),
    ),
    "cursor": PlatformSpec(
        name="cursor",
        scopes={
            "project": _scenario(
                "cursor",
                "project",
                (ExpectedPath("project", ".cursor/rules/graphify.mdc"),),
                install_command=("graphify", "cursor", "install"),
                uninstall_command=("graphify", "cursor", "uninstall"),
                equivalent_install_command=_generic_install_command("cursor", "project"),
            ),
        },
        unsupported_scopes={"user": "cursor install writes a project-local .cursor rule in the current working directory; sandbox covers that file effect as project scope"},
        uses_packaged_references=False,
        universal_uninstall_scopes=("project",),
    ),
    "devin": PlatformSpec(
        name="devin",
        user_skill=".config/devin/skills/graphify/SKILL.md",
        project_skill=".devin/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "devin",
                "user",
                (_skill("home", ".config/devin/skills/graphify/SKILL.md"),),
                uninstall_command=("graphify", "devin", "uninstall"),
                equivalent_install_command=("graphify", "devin", "install"),
            ),
            "project": _scenario(
                "devin",
                "project",
                (_skill("project", ".devin/skills/graphify/SKILL.md"), ExpectedPath("project", ".windsurf/rules/graphify.md")),
                equivalent_install_command=_direct_project_install("devin"),
            ),
        },
        universal_uninstall_scopes=("project",),
    ),
    "aider": PlatformSpec(
        name="aider",
        user_skill=".aider/graphify/SKILL.md",
        project_skill=".aider/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("aider", ".aider/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("aider", ".aider/graphify/SKILL.md"),
        },
    ),
    "copilot": PlatformSpec(
        name="copilot",
        user_skill=".copilot/skills/graphify/SKILL.md",
        project_skill=".copilot/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario("copilot", "user", (_skill("home", ".copilot/skills/graphify/SKILL.md"),), uninstall_command=("graphify", "copilot", "uninstall"), equivalent_install_command=("graphify", "copilot", "install")),
            "project": _skill_only_project_scope("copilot", ".copilot/skills/graphify/SKILL.md", equivalent=True),
        },
    ),
    "vscode": PlatformSpec(
        name="vscode",
        user_skill=".copilot/skills/graphify/SKILL.md",
        uses_packaged_references=False,
        reference_bundles=("vscode", "copilot"),
        scopes={
            "user": _scenario(
                "vscode",
                "user",
                (_skill("home", ".copilot/skills/graphify/SKILL.md"), _section("user_cwd", ".github/copilot-instructions.md")),
                install_command=("graphify", "vscode", "install"),
                uninstall_command=("graphify", "vscode", "uninstall"),
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE,),
            ),
            "project": _scenario(
                "vscode",
                "project",
                (_skill("home", ".copilot/skills/graphify/SKILL.md"), _section("project", ".github/copilot-instructions.md")),
                install_command=("graphify", "vscode", "install"),
                uninstall_command=("graphify", "vscode", "uninstall"),
                risk_notes=(MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,),
            ),
        },
        universal_uninstall_scopes=("user",),
    ),
    "claw": PlatformSpec(
        name="claw",
        user_skill=".openclaw/skills/graphify/SKILL.md",
        project_skill=".openclaw/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("claw", ".openclaw/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("claw", ".openclaw/skills/graphify/SKILL.md"),
        },
    ),
    "droid": PlatformSpec(
        name="droid",
        user_skill=".factory/skills/graphify/SKILL.md",
        project_skill=".factory/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("droid", ".factory/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("droid", ".factory/skills/graphify/SKILL.md"),
        },
    ),
    "trae": PlatformSpec(
        name="trae",
        user_skill=".trae/skills/graphify/SKILL.md",
        project_skill=".trae/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("trae", ".trae/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("trae", ".trae/skills/graphify/SKILL.md"),
        },
    ),
    "trae-cn": PlatformSpec(
        name="trae-cn",
        user_skill=".trae-cn/skills/graphify/SKILL.md",
        project_skill=".trae-cn/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("trae-cn", ".trae-cn/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("trae-cn", ".trae-cn/skills/graphify/SKILL.md"),
        },
    ),
    "hermes": PlatformSpec(
        name="hermes",
        user_skill=".hermes/skills/graphify/SKILL.md",
        project_skill=".hermes/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("hermes", ".hermes/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("hermes", ".hermes/skills/graphify/SKILL.md"),
        },
    ),
    "kiro": PlatformSpec(
        name="kiro",
        user_skill=".kiro/skills/graphify/SKILL.md",
        project_skill=".kiro/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("kiro", ".kiro/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _scenario(
                "kiro",
                "project",
                (_skill("project", ".kiro/skills/graphify/SKILL.md"), _section("project", ".kiro/steering/graphify.md", "graphify:")),
                install_command=("graphify", "kiro", "install"),
                uninstall_command=("graphify", "kiro", "uninstall"),
                equivalent_install_command=_generic_install_command("kiro", "project"),
            ),
        },
    ),
    "pi": PlatformSpec(
        name="pi",
        user_skill=".pi/agent/skills/graphify/SKILL.md",
        project_skill=".pi/agent/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario("pi", "user", (_skill("home", ".pi/agent/skills/graphify/SKILL.md"),), uninstall_command=("graphify", "pi", "uninstall"), equivalent_install_command=("graphify", "pi", "install")),
            "project": _skill_only_project_scope("pi", ".pi/agent/skills/graphify/SKILL.md", equivalent=True),
        },
    ),
    "antigravity": PlatformSpec(
        name="antigravity",
        user_skill=".gemini/config/skills/graphify/SKILL.md",
        project_skill=".agents/skills/graphify/SKILL.md",
        scopes={
            "user": _scenario(
                "antigravity",
                "user",
                (_skill("home", ".gemini/config/skills/graphify/SKILL.md"), _section("user_cwd", ".agents/rules/graphify.md"), ExpectedPath("user_cwd", ".agents/workflows/graphify.md")),
                install_command=("graphify", "antigravity", "install"),
                uninstall_command=("graphify", "antigravity", "uninstall"),
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE,),
            ),
            "project": _scenario(
                "antigravity",
                "project",
                (_skill("project", ".agents/skills/graphify/SKILL.md"), _section("project", ".agents/rules/graphify.md"), ExpectedPath("project", ".agents/workflows/graphify.md")),
                equivalent_install_command=_direct_project_install("antigravity"),
            ),
        },
        universal_uninstall_scopes=("user",),
    ),
    "antigravity-windows": PlatformSpec(
        name="antigravity-windows",
        user_skill=".gemini/config/skills/graphify/SKILL.md",
        project_skill=".agents/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("antigravity-windows", ".gemini/config/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE, SIMULATED_LINUX_LAYOUT_NOTE)),
            "project": _skill_only_project_scope("antigravity-windows", ".agents/skills/graphify/SKILL.md", notes=(SIMULATED_LINUX_LAYOUT_NOTE,)),
        },
        simulated_linux_layout=True,
    ),
    "windows": PlatformSpec(
        name="windows",
        user_skill=".claude/skills/graphify/SKILL.md",
        project_skill=".claude/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope(
                "windows",
                ".claude/skills/graphify/SKILL.md",
                extra_expected=(_section("home", ".claude/CLAUDE.md", "# graphify", remove_on_uninstall=False),),
                notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE, SIMULATED_LINUX_LAYOUT_NOTE),
            ),
            "project": _scenario(
                "windows",
                "project",
                (
                    _skill("project", ".claude/skills/graphify/SKILL.md"),
                    _section("project", ".claude/CLAUDE.md", "# graphify"),
                    _section("project", "CLAUDE.md"),
                    _json_marker("project", ".claude/settings.json"),
                ),
                risk_notes=(SIMULATED_LINUX_LAYOUT_NOTE,),
            ),
        },
        simulated_linux_layout=True,
    ),
    "kimi": PlatformSpec(
        name="kimi",
        user_skill=".kimi/skills/graphify/SKILL.md",
        project_skill=".kimi/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("kimi", ".kimi/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _skill_only_project_scope("kimi", ".kimi/skills/graphify/SKILL.md"),
        },
    ),
    "amp": PlatformSpec(
        name="amp",
        user_skill=".config/agents/skills/graphify/SKILL.md",
        project_skill=".agents/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope("amp", ".config/agents/skills/graphify/SKILL.md", notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,)),
            "project": _agents_project_scope("amp", ".agents/skills/graphify/SKILL.md"),
        },
    ),
}

ALL_PLATFORMS = list(SANDBOX_PLATFORM_SPECS)


def sandbox_platform_specs() -> dict[str, PlatformSpec]:
    return SANDBOX_PLATFORM_SPECS


def platform_spec(platform_name: str) -> PlatformSpec:
    try:
        return sandbox_platform_specs()[platform_name]
    except KeyError as exc:
        raise RuntimeError(f"unknown sandbox platform: {platform_name}") from exc


def user_skill(platform_name: str) -> ExpectedPath:
    skill = platform_spec(platform_name).user_skill
    if skill is None:
        raise RuntimeError(f"sandbox platform has no user skill path: {platform_name}")
    return ExpectedPath("home", skill)


def project_skill(platform_name: str) -> ExpectedPath:
    skill = platform_spec(platform_name).project_skill
    if skill is None:
        raise RuntimeError(f"sandbox platform has no project skill path: {platform_name}")
    return ExpectedPath("project", skill)


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return platform_spec(platform_name).unsupported_scopes.get(scope)


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    scope = platform_spec(platform_name).scopes.get("user")
    return None if scope is None else scope.uninstall_command


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return _generic_install_command(platform_name, scope)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    scope_spec = platform_spec(platform_name).scopes.get(scope)
    if scope_spec is None:
        return None
    generic = generic_install_command(platform_name, scope)
    alternate = scope_spec.equivalent_install_command
    if scope_spec.install_command != generic:
        return scope_spec.install_command
    if alternate is not None and alternate != generic:
        return alternate
    return None


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    scope_spec = platform_spec(scenario.platform).scopes.get(scenario.scope)
    if scope_spec is None or scope_spec.equivalent_install_command is None:
        return None
    if scenario.install_command == scope_spec.install_command:
        return scope_spec.equivalent_install_command
    if scenario.install_command == scope_spec.equivalent_install_command:
        return scope_spec.install_command
    return None


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    equivalent = equivalent_install_command(scenario)
    if equivalent is not None:
        return {"status": "runnable", "command": list(equivalent)}
    return {
        "status": "not_applicable",
        "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
    }


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    scopes = ["user", "project"] if scope == "both" else [scope]
    scenarios: list[Scenario] = []
    for one_scope in scopes:
        scenario = make_scenario(platform_name, one_scope)
        if scenario is not None:
            scenarios.append(scenario)
    return scenarios


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    spec = platform_spec(platform_name)
    if scope in spec.unsupported_scopes:
        return None
    scope_spec = spec.scopes.get(scope)
    if scope_spec is None:
        return None
    return Scenario(
        platform=spec.name,
        scope=scope,
        install_command=scope_spec.install_command,
        uninstall_command=scope_spec.uninstall_command,
        cwd_root=scope_spec.cwd_root,
        expected=scope_spec.expected,
        risk_notes=scope_spec.risk_notes,
    )


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    ordered = list(notes)
    spec = SANDBOX_PLATFORM_SPECS.get(platform_name or "")
    if spec is not None and spec.simulated_linux_layout:
        ordered.append(SIMULATED_LINUX_LAYOUT_NOTE)
    return _dedupe_notes(*ordered)
