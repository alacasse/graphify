from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


GRAPHIFY_MARKER = "## graphify"
PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE = "public_cli_lacks_user_skill_uninstall"
MIXED_SCOPE_PROJECT_WIRING_NOTE = "mixed_scope_project_wiring"
MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE = "mixed_scope_global_skill_plus_project_wiring"
SIMULATED_LINUX_LAYOUT_NOTE = "simulated_linux_file_layout_only"


@dataclass(frozen=True)
class JsonHookExpectation:
    event: str
    matcher: str
    detail_name: str
    required_fragments: tuple[str, ...] = ("graphify",)


@dataclass(frozen=True)
class JsonPluginExpectation:
    expected_entry: str
    allow_file_uri: bool = False
    detail_name: str = "plugin_present"


@dataclass(frozen=True)
class JsonExpectation:
    schema_name: str
    hooks: tuple[JsonHookExpectation, ...] = ()
    plugin: JsonPluginExpectation | None = None


@dataclass(frozen=True)
class TextExpectation:
    preserve_user_content: bool = False
    repair_stale_graphify_section: bool = False
    remove_graphify_section_on_uninstall: bool = True
    require_user_content_on_uninstall: bool = False


@dataclass(frozen=True)
class SkillSidecarExpectation:
    version_name: str = ".graphify_version"
    references_dir: str = "references"
    references_tmp_dir: str = "references.tmp"
    reference_pointer_pattern: str = r"references/([A-Za-z0-9_.-]+\.md)\b"


@dataclass(frozen=True)
class GeneratedFileExpectation:
    relative_substrings: tuple[str, ...] = ("graphify",)
    text_suffixes: tuple[str, ...] = (".json", ".js", ".md", ".mdc", ".txt", "")
    content_markers: tuple[str, ...] = ("graphify",)
    include_user_content_sentinel: bool = True
    max_text_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class InstallCommandVariant:
    label: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class TargetRuntimeValidationSpec:
    section_title: str
    status: str
    strategy: str
    targets: tuple[str, ...]
    notes: tuple[str, ...]
    evidence_path: str | None = None

    def to_manifest(self) -> dict[str, object]:
        return {
            "section_title": self.section_title,
            "status": self.status,
            "evidence_path": self.evidence_path,
            "strategy": self.strategy,
            "targets": list(self.targets),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class UniversalUninstallScenarioSpec:
    scenario_id: str
    platform_label: str
    scope: str
    command: tuple[str, ...]
    cwd_root: str
    eligible_platform_scope: str
    minimum_installed_scenarios: int = 2
    artifact_subdir: str = "uninstall"
    risk_note: str = "universal uninstall covers Graphify-owned file effects after multiple installs"


@dataclass(frozen=True)
class SelectedUniversalUninstallScenario:
    spec: UniversalUninstallScenarioSpec
    installed_scenarios: tuple[Scenario, ...]


@dataclass(frozen=True)
class DisposableSeedFile:
    relative: str
    content: str


@dataclass(frozen=True)
class DisposableArtifactScenarioSpec:
    scenario_id: str
    platform_label: str
    scope: str
    command: tuple[str, ...]
    cwd_root: str
    artifact_subdir: str
    disposable_path_root: str
    disposable_path_relative: str
    seed_files: tuple[DisposableSeedFile, ...]
    scope_eligibility: tuple[str, ...]
    risk_note: str


@dataclass(frozen=True)
class ExpectedPath:
    root: str
    relative: str
    kind: str = "file"
    content_kind: Literal["text", "json"] = "text"
    marker: str | None = None
    remove_on_uninstall: bool = True
    json_expectation: JsonExpectation | None = None
    text_expectation: TextExpectation = field(default_factory=TextExpectation)
    skill_sidecar_expectation: SkillSidecarExpectation | None = None


@dataclass(frozen=True)
class Scenario:
    platform: str
    scope: str
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[ExpectedPath, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    allowed_roots: tuple[str, ...] = ()
    generated_file_expectation: GeneratedFileExpectation = field(default_factory=GeneratedFileExpectation)


@dataclass(frozen=True)
class ScopeSpec:
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[ExpectedPath, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    equivalent_install_command: tuple[str, ...] | None = None
    install_variants: tuple[InstallCommandVariant, ...] = ()
    allowed_roots: tuple[str, ...] = ()
    generated_file_expectation: GeneratedFileExpectation = field(default_factory=GeneratedFileExpectation)


@dataclass(frozen=True)
class ReferenceBundle:
    name: str
    required_package_relative: str | None = None

    def is_eligible(self, package_dir: Path) -> bool:
        return self.required_package_relative is None or (package_dir / self.required_package_relative).exists()


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    user_skill: str | None = None
    project_skill: str | None = None
    scopes: dict[str, ScopeSpec] = field(default_factory=dict)
    unsupported_scopes: dict[str, str] = field(default_factory=dict)
    uses_packaged_references: bool = True
    reference_bundles: tuple[ReferenceBundle, ...] = ()
    simulated_linux_layout: bool = False
    universal_uninstall_scopes: tuple[str, ...] = ()
    target_runtime_validation: tuple[TargetRuntimeValidationSpec, ...] = ()


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


def _declared_install_variants(
    platform_name: str,
    scope: str,
    install_command: tuple[str, ...],
    equivalent_install_command: tuple[str, ...] | None,
) -> tuple[InstallCommandVariant, ...]:
    generic = _generic_install_command(platform_name, scope)
    direct = _direct_project_install(platform_name) if scope == "project" else ("graphify", platform_name, "install")

    def label(command: tuple[str, ...], fallback: str) -> str:
        if command == generic:
            return "generic"
        if command == direct:
            return "direct"
        return fallback

    variants = [InstallCommandVariant(label(install_command, "primary"), install_command)]
    if equivalent_install_command is not None:
        variants.append(InstallCommandVariant(label(equivalent_install_command, "alternate"), equivalent_install_command))
    return tuple(variants)


def _skill(root: str, relative: str) -> ExpectedPath:
    return ExpectedPath(root, relative, skill_sidecar_expectation=SkillSidecarExpectation())


def _section(
    root: str,
    relative: str,
    marker: str = GRAPHIFY_MARKER,
    *,
    preserve_user_content: bool = False,
    repair_stale_graphify_section: bool = True,
    remove_on_uninstall: bool = True,
) -> ExpectedPath:
    return ExpectedPath(
        root,
        relative,
        marker=marker,
        remove_on_uninstall=remove_on_uninstall,
        text_expectation=TextExpectation(
            preserve_user_content=preserve_user_content,
            repair_stale_graphify_section=repair_stale_graphify_section,
            require_user_content_on_uninstall=preserve_user_content,
        ),
    )


def _json_marker(root: str, relative: str, *, expectation: JsonExpectation | None = None) -> ExpectedPath:
    return ExpectedPath(root, relative, content_kind="json", marker="graphify", json_expectation=expectation)


def _json_hooks(root: str, relative: str, schema_name: str, hooks: tuple[JsonHookExpectation, ...]) -> ExpectedPath:
    return _json_marker(root, relative, expectation=JsonExpectation(schema_name=schema_name, hooks=hooks))


def _json_plugin(root: str, relative: str, schema_name: str, plugin_relative: str, *, allow_file_uri: bool = False) -> ExpectedPath:
    return _json_marker(
        root,
        relative,
        expectation=JsonExpectation(
            schema_name=schema_name,
            plugin=JsonPluginExpectation(expected_entry=plugin_relative, allow_file_uri=allow_file_uri),
        ),
    )


def _plugin(root: str, relative: str) -> ExpectedPath:
    return ExpectedPath(root, relative)


def _project_plugin_config(plugin_relative: str, config_relative: str, schema_name: str, *, allow_file_uri: bool = False) -> tuple[ExpectedPath, ExpectedPath]:
    return (_plugin("project", plugin_relative), _json_plugin("project", config_relative, schema_name, plugin_relative, allow_file_uri=allow_file_uri))


def _cwd_plugin_config(plugin_relative: str, config_relative: str, schema_name: str, *, allow_file_uri: bool = False) -> tuple[ExpectedPath, ExpectedPath]:
    return (_plugin("user_cwd", plugin_relative), _json_plugin("user_cwd", config_relative, schema_name, plugin_relative, allow_file_uri=allow_file_uri))


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
    if scope == "project":
        allowed_roots = ("project",)
        if MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE in risk_notes:
            allowed_roots = ("home", "project", "user_cwd")
    else:
        allowed_roots = ("home",)
        if MIXED_SCOPE_PROJECT_WIRING_NOTE in risk_notes:
            allowed_roots = ("home", "project", "user_cwd")
    declared_install = install_command or _generic_install_command(platform_name, scope)
    return ScopeSpec(
        install_command=declared_install,
        uninstall_command=uninstall,
        cwd_root=cwd_root or ("project" if scope == "project" else "user_cwd"),
        expected=expected,
        risk_notes=risk_notes,
        equivalent_install_command=equivalent_install_command,
        install_variants=_declared_install_variants(platform_name, scope, declared_install, equivalent_install_command),
        allowed_roots=allowed_roots,
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
        (_skill("project", skill_relative), _section("project", "AGENTS.md", preserve_user_content=True), *extra_expected),
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


@dataclass(frozen=True)
class ScenarioRegistry:
    specs: dict[str, PlatformSpec]
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...] = ()
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...] = ()

    @property
    def platform_names(self) -> list[str]:
        return list(self.specs)

    def platform_spec(self, platform_name: str) -> PlatformSpec:
        try:
            return self.specs[platform_name]
        except KeyError as exc:
            raise RuntimeError(f"unknown sandbox platform: {platform_name}") from exc

    def selected_scopes(self, scope: str) -> list[str]:
        return ["user", "project"] if scope == "both" else [scope]

    def selected_platforms(self, *, all_platforms: bool, platform_name: str | None) -> list[str]:
        platforms = self.platform_names if all_platforms else [platform_name]
        unknown = [name for name in platforms if name not in self.specs]
        if unknown:
            raise RuntimeError(f"unknown sandbox platform(s): {', '.join(str(name) for name in unknown)}")
        return [str(name) for name in platforms]

    def user_skill(self, platform_name: str) -> ExpectedPath:
        skill = self.platform_spec(platform_name).user_skill
        if skill is None:
            raise RuntimeError(f"sandbox platform has no user skill path: {platform_name}")
        return _skill("home", skill)

    def project_skill(self, platform_name: str) -> ExpectedPath:
        skill = self.platform_spec(platform_name).project_skill
        if skill is None:
            raise RuntimeError(f"sandbox platform has no project skill path: {platform_name}")
        return _skill("project", skill)

    def unsupported_scope_reason(self, platform_name: str, scope: str) -> str | None:
        return self.platform_spec(platform_name).unsupported_scopes.get(scope)

    def direct_uninstall_command(self, platform_name: str) -> tuple[str, ...] | None:
        scope = self.platform_spec(platform_name).scopes.get("user")
        return None if scope is None else scope.uninstall_command

    def generic_install_command(self, platform_name: str, scope: str) -> tuple[str, ...]:
        return _generic_install_command(platform_name, scope)

    def direct_install_command(self, platform_name: str, scope: str) -> tuple[str, ...] | None:
        scope_spec = self.platform_spec(platform_name).scopes.get(scope)
        if scope_spec is None:
            return None
        for variant in self.install_variants_for_scope(platform_name, scope):
            if variant.label == "direct":
                return variant.command
        return None

    def install_variants_for_scope(self, platform_name: str, scope: str) -> tuple[InstallCommandVariant, ...]:
        scope_spec = self.platform_spec(platform_name).scopes.get(scope)
        if scope_spec is None:
            return ()
        if scope_spec.install_variants:
            return scope_spec.install_variants
        variants = [InstallCommandVariant("primary", scope_spec.install_command)]
        if scope_spec.equivalent_install_command is not None:
            variants.append(InstallCommandVariant("alternate", scope_spec.equivalent_install_command))
        return tuple(variants)

    def install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, ...]:
        return self.install_variants_for_scope(scenario.platform, scenario.scope)

    def make_scenario(self, platform_name: str, scope: str) -> Scenario | None:
        spec = self.platform_spec(platform_name)
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
            allowed_roots=scope_spec.allowed_roots,
            generated_file_expectation=scope_spec.generated_file_expectation,
        )

    def platform_scenarios(self, platform_name: str, scope: str) -> list[Scenario]:
        return [scenario for one_scope in self.selected_scopes(scope) if (scenario := self.make_scenario(platform_name, one_scope)) is not None]

    def equivalent_install_command(self, scenario: Scenario) -> tuple[str, ...] | None:
        variants = self.install_variants(scenario)
        if len(variants) < 2:
            return None
        for variant in variants:
            if scenario.install_command == variant.command:
                return next((candidate.command for candidate in variants if candidate.command != variant.command), None)
        return None

    def equivalent_install_variants(self, scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
        variants = self.install_variants(scenario)
        if len(variants) < 2:
            return None
        primary = next((variant for variant in variants if variant.command == scenario.install_command), variants[0])
        alternate = next((variant for variant in variants if variant.command != primary.command), None)
        if alternate is None:
            return None
        return primary, alternate

    def equivalence_status(self, scenario: Scenario) -> dict[str, object]:
        equivalent = self.equivalent_install_command(scenario)
        if equivalent is not None:
            return {"status": "runnable", "command": list(equivalent)}
        return {
            "status": "not_applicable",
            "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
        }

    def scenario_id(self, platform_name: str, scope: str) -> str:
        raw = f"{platform_name}-{scope}".lower()
        safe = re.sub(r"[^a-z0-9_.-]+", "-", raw)
        safe = re.sub(r"[-_.]{2,}", "-", safe).strip(".-_")
        return safe or "scenario"

    def universal_uninstall_scenario_id(self, scope: str) -> str:
        spec = self.universal_uninstall_spec_for_scope(scope)
        return spec.scenario_id if spec is not None else f"universal-uninstall-{scope}"

    def purge_disposable_graphify_out_scenario_id(self) -> str:
        for spec in self.disposable_artifact_specs:
            if spec.disposable_path_relative == "graphify-out":
                return spec.scenario_id
        return "purge-disposable-graphify-out"

    def coverage_records(self, platforms: list[str], scope: str) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for platform_name in platforms:
            for one_scope in self.selected_scopes(scope):
                reason = self.unsupported_scope_reason(platform_name, one_scope)
                scenario = self.make_scenario(platform_name, one_scope) if reason is None else None
                if scenario is not None:
                    records.append(
                        {
                            "platform": platform_name,
                            "scope": one_scope,
                            "status": "runnable",
                            "scenario_id": self.scenario_id(platform_name, one_scope),
                            "install_command": list(scenario.install_command),
                            "uninstall_command": None if scenario.uninstall_command is None else list(scenario.uninstall_command),
                            "generic_direct_equivalence": self.equivalence_status(scenario),
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

    def universal_uninstall_spec_for_scope(self, scope: str) -> UniversalUninstallScenarioSpec | None:
        return next((spec for spec in self.universal_uninstall_specs if spec.scope == scope), None)

    def universal_uninstall_scenarios(self, platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
        requested = set(platforms)
        selected_scopes = set(self.selected_scopes(scope))
        selected: list[SelectedUniversalUninstallScenario] = []
        for universal_spec in self.universal_uninstall_specs:
            if universal_spec.scope not in selected_scopes:
                continue
            scenarios = [
                self.make_scenario(platform_name, universal_spec.eligible_platform_scope)
                for platform_name, spec in self.specs.items()
                if platform_name in requested and universal_spec.eligible_platform_scope in spec.universal_uninstall_scopes
            ]
            runnable = tuple(scenario for scenario in scenarios if scenario is not None)
            if len(runnable) >= universal_spec.minimum_installed_scenarios:
                selected.append(SelectedUniversalUninstallScenario(universal_spec, runnable))
        return selected

    def universal_uninstall_groups(self, platforms: list[str], scope: str) -> list[tuple[str, list[Scenario]]]:
        return [(selected.spec.scope, list(selected.installed_scenarios)) for selected in self.universal_uninstall_scenarios(platforms, scope)]

    def disposable_artifact_scenarios(self, scope: str) -> list[DisposableArtifactScenarioSpec]:
        return [spec for spec in self.disposable_artifact_specs if scope in spec.scope_eligibility]

    def target_runtime_validation_sections(self) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for platform in self.specs.values():
            for validation in platform.target_runtime_validation:
                key = (validation.section_title, validation.status)
                if key in seen:
                    continue
                seen.add(key)
                sections.append(validation.to_manifest())
        return sections

    def validate_roots(self, declared_roots: set[str]) -> None:
        unknown: set[str] = set()
        for platform in self.specs.values():
            for scope in platform.scopes.values():
                if scope.cwd_root not in declared_roots:
                    unknown.add(scope.cwd_root)
                unknown.update(entry.root for entry in scope.expected if entry.root not in declared_roots)
        unknown.update(spec.cwd_root for spec in self.universal_uninstall_specs if spec.cwd_root not in declared_roots)
        for spec in self.disposable_artifact_specs:
            if spec.cwd_root not in declared_roots:
                unknown.add(spec.cwd_root)
            if spec.disposable_path_root not in declared_roots:
                unknown.add(spec.disposable_path_root)
        if unknown:
            raise RuntimeError(f"unknown sandbox root declaration(s): {', '.join(sorted(unknown))}")

    def risk_notes(self, *notes: str, platform_name: str | None = None) -> tuple[str, ...]:
        ordered = list(notes)
        spec = self.specs.get(platform_name or "")
        if spec is not None and spec.simulated_linux_layout:
            ordered.append(SIMULATED_LINUX_LAYOUT_NOTE)
        return _dedupe_notes(*ordered)


# Temporary sandbox-owned source of platform file effects. The app installer
# refactor should eventually expose an app-owned install plan that this adapter
# can consume instead of maintaining sandbox-local tool specifics.
WINDOWS_TARGET_RUNTIME_VALIDATION = TargetRuntimeValidationSpec(
    section_title="Windows Validation",
    status="payload_consistency_only",
    evidence_path=None,
    strategy="Linux Docker validates Windows-named payload consistency only; real Windows runtime/path semantics require separate Windows validation",
    targets=(
        "windows payload file-effect simulation",
        "antigravity remapping to antigravity-windows",
        "Windows-specific skill payload and references generation",
        "payload consistency for explicit Windows platform selection",
    ),
    notes=(
        "Linux sandbox results for windows and antigravity-windows check packaged payloads, references, and generated file consistency only.",
        "This does not validate Windows Path.home(), PowerShell/cmd entrypoints, cleanup semantics, permissions, or target-app discovery.",
    ),
)


SANDBOX_PLATFORM_SPECS: dict[str, PlatformSpec] = {
    "claude": PlatformSpec(
        name="claude",
        user_skill=".claude/skills/graphify/SKILL.md",
        project_skill=".claude/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope(
                "claude",
                ".claude/skills/graphify/SKILL.md",
                extra_expected=(_section("home", ".claude/CLAUDE.md", "# graphify", preserve_user_content=True, repair_stale_graphify_section=False, remove_on_uninstall=False),),
                notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,),
            ),
            "project": _scenario(
                "claude",
                "project",
                (
                    _skill("project", ".claude/skills/graphify/SKILL.md"),
                    _section("project", ".claude/CLAUDE.md", "# graphify", preserve_user_content=True, repair_stale_graphify_section=False),
                    _section("project", "CLAUDE.md", preserve_user_content=True),
                    _json_hooks(
                        "project",
                        ".claude/settings.json",
                        "claude_settings",
                        (
                            JsonHookExpectation(event="PreToolUse", matcher="Bash", detail_name="bash_hook_present"),
                            JsonHookExpectation(event="PreToolUse", matcher="Read|Glob", detail_name="read_glob_hook_present"),
                        ),
                    ),
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
            "project": _agents_project_scope(
                "codex",
                ".codex/skills/graphify/SKILL.md",
                extra_expected=(
                    _json_hooks(
                        "project",
                        ".codex/hooks.json",
                        "codex_hooks",
                        (JsonHookExpectation(event="PreToolUse", matcher="Bash", detail_name="graphify_hook_present", required_fragments=("graphify", "hook-check")),),
                    ),
                ),
            ),
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
                    _json_hooks(
                        "home",
                        ".codebuddy/settings.json",
                        "codebuddy_settings",
                        (
                            JsonHookExpectation(event="PreToolUse", matcher="Bash", detail_name="bash_hook_present"),
                            JsonHookExpectation(event="PreToolUse", matcher="Read|Glob", detail_name="read_glob_hook_present"),
                        ),
                    ),
                ),
                uninstall_command=("graphify", "uninstall"),
            ),
            "project": _scenario(
                "codebuddy",
                "project",
                (
                    _skill("project", ".codebuddy/skills/graphify/SKILL.md"),
                    _section("project", "CODEBUDDY.md"),
                    _json_hooks(
                        "project",
                        ".codebuddy/settings.json",
                        "codebuddy_settings",
                        (
                            JsonHookExpectation(event="PreToolUse", matcher="Bash", detail_name="bash_hook_present"),
                            JsonHookExpectation(event="PreToolUse", matcher="Read|Glob", detail_name="read_glob_hook_present"),
                        ),
                    ),
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
                    *_cwd_plugin_config(".opencode/plugins/graphify.js", ".opencode/opencode.json", "opencode_config"),
                ),
                uninstall_command=None,
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE, PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE),
            ),
            "project": _agents_project_scope(
                "opencode",
                ".opencode/skills/graphify/SKILL.md",
                extra_expected=_project_plugin_config(".opencode/plugins/graphify.js", ".opencode/opencode.json", "opencode_config"),
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
                    _section("project", "AGENTS.md", preserve_user_content=True),
                    *_project_plugin_config(".kilo/plugins/graphify.js", ".kilo/kilo.json", "kilo_config", allow_file_uri=True),
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
                    _section("user_cwd", "GEMINI.md", preserve_user_content=True),
                    _json_hooks(
                        "user_cwd",
                        ".gemini/settings.json",
                        "gemini_settings",
                        (JsonHookExpectation(event="BeforeTool", matcher="read_file|list_directory", detail_name="graphify_hook_present"),),
                    ),
                ),
                uninstall_command=("graphify", "gemini", "uninstall"),
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE,),
                equivalent_install_command=("graphify", "gemini", "install"),
            ),
            "project": _scenario(
                "gemini",
                "project",
                (
                    _skill("project", ".gemini/skills/graphify/SKILL.md"),
                    _section("project", "GEMINI.md", preserve_user_content=True),
                    _json_hooks(
                        "project",
                        ".gemini/settings.json",
                        "gemini_settings",
                        (JsonHookExpectation(event="BeforeTool", matcher="read_file|list_directory", detail_name="graphify_hook_present"),),
                    ),
                ),
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
        reference_bundles=(
            ReferenceBundle("vscode", required_package_relative="skill-vscode.md"),
            ReferenceBundle("copilot"),
        ),
        scopes={
            "user": _scenario(
                "vscode",
                "user",
                (_skill("home", ".copilot/skills/graphify/SKILL.md"), _section("user_cwd", ".github/copilot-instructions.md", preserve_user_content=True)),
                install_command=("graphify", "vscode", "install"),
                uninstall_command=("graphify", "vscode", "uninstall"),
                risk_notes=(MIXED_SCOPE_PROJECT_WIRING_NOTE,),
            ),
            "project": _scenario(
                "vscode",
                "project",
                (_skill("home", ".copilot/skills/graphify/SKILL.md"), _section("project", ".github/copilot-instructions.md", preserve_user_content=True)),
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
                (_skill("project", ".kiro/skills/graphify/SKILL.md"), _section("project", ".kiro/steering/graphify.md", "graphify:", repair_stale_graphify_section=False)),
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
        target_runtime_validation=(WINDOWS_TARGET_RUNTIME_VALIDATION,),
    ),
    "windows": PlatformSpec(
        name="windows",
        user_skill=".claude/skills/graphify/SKILL.md",
        project_skill=".claude/skills/graphify/SKILL.md",
        scopes={
            "user": _generic_user_scope(
                "windows",
                ".claude/skills/graphify/SKILL.md",
                extra_expected=(_section("home", ".claude/CLAUDE.md", "# graphify", preserve_user_content=True, repair_stale_graphify_section=False, remove_on_uninstall=False),),
                notes=(PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE, SIMULATED_LINUX_LAYOUT_NOTE),
            ),
            "project": _scenario(
                "windows",
                "project",
                (
                    _skill("project", ".claude/skills/graphify/SKILL.md"),
                    _section("project", ".claude/CLAUDE.md", "# graphify", preserve_user_content=True, repair_stale_graphify_section=False),
                    _section("project", "CLAUDE.md", preserve_user_content=True),
                    _json_hooks(
                        "project",
                        ".claude/settings.json",
                        "claude_settings",
                        (
                            JsonHookExpectation(event="PreToolUse", matcher="Bash", detail_name="bash_hook_present"),
                            JsonHookExpectation(event="PreToolUse", matcher="Read|Glob", detail_name="read_glob_hook_present"),
                        ),
                    ),
                ),
                risk_notes=(SIMULATED_LINUX_LAYOUT_NOTE,),
            ),
        },
        simulated_linux_layout=True,
        target_runtime_validation=(WINDOWS_TARGET_RUNTIME_VALIDATION,),
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

_PYTHON_SANDBOX_PLATFORM_SPECS = SANDBOX_PLATFORM_SPECS

DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS = (
    UniversalUninstallScenarioSpec(
        scenario_id="universal-uninstall-user",
        platform_label="multiple",
        scope="user",
        command=("graphify", "uninstall"),
        cwd_root="user_cwd",
        eligible_platform_scope="user",
    ),
    UniversalUninstallScenarioSpec(
        scenario_id="universal-uninstall-project",
        platform_label="multiple",
        scope="project",
        command=("graphify", "uninstall", "--project"),
        cwd_root="project",
        eligible_platform_scope="project",
    ),
)

DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS = (
    DisposableArtifactScenarioSpec(
        scenario_id="purge-disposable-graphify-out",
        platform_label="purge",
        scope="project",
        command=("graphify", "uninstall", "--purge"),
        cwd_root="project",
        artifact_subdir="uninstall-purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(DisposableSeedFile("graph.json", '{"nodes": [], "edges": []}\n'),),
        scope_eligibility=("project", "both"),
        risk_note="purge verified only against disposable sandbox graphify-out state",
    ),
)


_PYTHON_DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS = DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS
_PYTHON_DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS = DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS


def _python_default_scenario_registry() -> ScenarioRegistry:
    return ScenarioRegistry(
        _PYTHON_SANDBOX_PLATFORM_SPECS,
        universal_uninstall_specs=_PYTHON_DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS,
        disposable_artifact_specs=_PYTHON_DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS,
    )


try:
    from .spec_loader import load_default_registry
except ImportError:  # pragma: no cover - direct script import fallback
    from spec_loader import load_default_registry  # type: ignore[no-redef]


DEFAULT_SCENARIO_REGISTRY = load_default_registry()
SANDBOX_PLATFORM_SPECS = DEFAULT_SCENARIO_REGISTRY.specs
DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS = DEFAULT_SCENARIO_REGISTRY.universal_uninstall_specs
DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS = DEFAULT_SCENARIO_REGISTRY.disposable_artifact_specs
ALL_PLATFORMS = list(SANDBOX_PLATFORM_SPECS)


def sandbox_platform_specs() -> dict[str, PlatformSpec]:
    return DEFAULT_SCENARIO_REGISTRY.specs


def platform_spec(platform_name: str) -> PlatformSpec:
    return DEFAULT_SCENARIO_REGISTRY.platform_spec(platform_name)


def user_skill(platform_name: str) -> ExpectedPath:
    return DEFAULT_SCENARIO_REGISTRY.user_skill(platform_name)


def project_skill(platform_name: str) -> ExpectedPath:
    return DEFAULT_SCENARIO_REGISTRY.project_skill(platform_name)


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return DEFAULT_SCENARIO_REGISTRY.unsupported_scope_reason(platform_name, scope)


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    return DEFAULT_SCENARIO_REGISTRY.direct_uninstall_command(platform_name)


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return DEFAULT_SCENARIO_REGISTRY.generic_install_command(platform_name, scope)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    return DEFAULT_SCENARIO_REGISTRY.direct_install_command(platform_name, scope)


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    return DEFAULT_SCENARIO_REGISTRY.equivalent_install_command(scenario)


def equivalent_install_variants(scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    return DEFAULT_SCENARIO_REGISTRY.equivalent_install_variants(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return DEFAULT_SCENARIO_REGISTRY.equivalence_status(scenario)


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    return DEFAULT_SCENARIO_REGISTRY.platform_scenarios(platform_name, scope)


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    return DEFAULT_SCENARIO_REGISTRY.make_scenario(platform_name, scope)


def target_runtime_validation_sections() -> list[dict[str, object]]:
    return DEFAULT_SCENARIO_REGISTRY.target_runtime_validation_sections()


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
    return DEFAULT_SCENARIO_REGISTRY.universal_uninstall_scenarios(platforms, scope)


def disposable_artifact_scenarios(scope: str) -> list[DisposableArtifactScenarioSpec]:
    return DEFAULT_SCENARIO_REGISTRY.disposable_artifact_scenarios(scope)


def validate_roots(declared_roots: set[str]) -> None:
    DEFAULT_SCENARIO_REGISTRY.validate_roots(declared_roots)


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    return DEFAULT_SCENARIO_REGISTRY.risk_notes(*notes, platform_name=platform_name)
