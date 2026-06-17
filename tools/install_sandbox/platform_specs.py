from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

try:
    from .expected_effects import (
        ExpectedPath,
        FileEffect,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        SkillEffect,
        SkillSidecarExpectation,
        TextExpectation,
        TextSectionEffect,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import (  # type: ignore[no-redef]
        ExpectedPath,
        FileEffect,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        SkillEffect,
        SkillSidecarExpectation,
        TextExpectation,
        TextSectionEffect,
    )


GRAPHIFY_MARKER = "## graphify"
PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE = "public_cli_lacks_user_skill_uninstall"
MIXED_SCOPE_PROJECT_WIRING_NOTE = "mixed_scope_project_wiring"
MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE = "mixed_scope_global_skill_plus_project_wiring"
SIMULATED_LINUX_LAYOUT_NOTE = "simulated_linux_file_layout_only"


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
class Scenario:
    platform: str
    scope: str
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[InstallSurface, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    allowed_roots: tuple[str, ...] = ()
    generated_file_expectation: GeneratedFileExpectation = field(default_factory=GeneratedFileExpectation)


@dataclass(frozen=True)
class ScopeSpec:
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[InstallSurface, ...]
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


def _skill(root: str, relative: str) -> InstallSurface:
    return SkillEffect(root, relative)


def _scenario(
    platform_name: str,
    scope: str,
    expected: tuple[InstallSurface, ...],
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

    def user_skill(self, platform_name: str) -> InstallSurface:
        skill = self.platform_spec(platform_name).user_skill
        if skill is None:
            raise RuntimeError(f"sandbox platform has no user skill path: {platform_name}")
        return _skill("home", skill)

    def project_skill(self, platform_name: str) -> InstallSurface:
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


_DEFAULT_SCENARIO_REGISTRY: ScenarioRegistry | None = None
_LAZY_DEFAULT_NAMES = {
    "DEFAULT_SCENARIO_REGISTRY",
    "SANDBOX_PLATFORM_SPECS",
    "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS",
    "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS",
    "ALL_PLATFORMS",
}


def _import_load_default_registry():
    try:
        from .spec_loader import load_default_registry
    except ImportError:  # pragma: no cover - direct script import fallback
        from spec_loader import load_default_registry  # type: ignore[no-redef]
    return load_default_registry


def _load_default_scenario_registry() -> ScenarioRegistry:
    global _DEFAULT_SCENARIO_REGISTRY
    if _DEFAULT_SCENARIO_REGISTRY is None:
        _DEFAULT_SCENARIO_REGISTRY = _import_load_default_registry()()
    return _DEFAULT_SCENARIO_REGISTRY


def _default_export(name: str):
    registry = _load_default_scenario_registry()
    if name == "DEFAULT_SCENARIO_REGISTRY":
        return registry
    if name == "SANDBOX_PLATFORM_SPECS":
        return registry.specs
    if name == "DEFAULT_UNIVERSAL_UNINSTALL_SCENARIOS":
        return registry.universal_uninstall_specs
    if name == "DEFAULT_DISPOSABLE_ARTIFACT_SCENARIOS":
        return registry.disposable_artifact_specs
    if name == "ALL_PLATFORMS":
        return list(registry.specs)
    raise AttributeError(name)


def __getattr__(name: str):
    if name in _LAZY_DEFAULT_NAMES:
        value = _default_export(name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def sandbox_platform_specs() -> dict[str, PlatformSpec]:
    return _load_default_scenario_registry().specs


def platform_spec(platform_name: str) -> PlatformSpec:
    return _load_default_scenario_registry().platform_spec(platform_name)


def user_skill(platform_name: str) -> InstallSurface:
    return _load_default_scenario_registry().user_skill(platform_name)


def project_skill(platform_name: str) -> InstallSurface:
    return _load_default_scenario_registry().project_skill(platform_name)


def unsupported_scope_reason(platform_name: str, scope: str) -> str | None:
    return _load_default_scenario_registry().unsupported_scope_reason(platform_name, scope)


def direct_uninstall_command(platform_name: str) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().direct_uninstall_command(platform_name)


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return _load_default_scenario_registry().generic_install_command(platform_name, scope)


def direct_install_command(platform_name: str, scope: str) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().direct_install_command(platform_name, scope)


def equivalent_install_command(scenario: Scenario) -> tuple[str, ...] | None:
    return _load_default_scenario_registry().equivalent_install_command(scenario)


def equivalent_install_variants(scenario: Scenario) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    return _load_default_scenario_registry().equivalent_install_variants(scenario)


def equivalence_status(scenario: Scenario) -> dict[str, object]:
    return _load_default_scenario_registry().equivalence_status(scenario)


def platform_scenarios(platform_name: str, scope: str) -> list[Scenario]:
    return _load_default_scenario_registry().platform_scenarios(platform_name, scope)


def make_scenario(platform_name: str, scope: str) -> Scenario | None:
    return _load_default_scenario_registry().make_scenario(platform_name, scope)


def target_runtime_validation_sections() -> list[dict[str, object]]:
    return _load_default_scenario_registry().target_runtime_validation_sections()


def universal_uninstall_scenarios(platforms: list[str], scope: str) -> list[SelectedUniversalUninstallScenario]:
    return _load_default_scenario_registry().universal_uninstall_scenarios(platforms, scope)


def disposable_artifact_scenarios(scope: str) -> list[DisposableArtifactScenarioSpec]:
    return _load_default_scenario_registry().disposable_artifact_scenarios(scope)


def validate_roots(declared_roots: set[str]) -> None:
    _load_default_scenario_registry().validate_roots(declared_roots)


def risk_notes(*notes: str, platform_name: str | None = None) -> tuple[str, ...]:
    return _load_default_scenario_registry().risk_notes(*notes, platform_name=platform_name)
