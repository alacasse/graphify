from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

try:
    from .harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry
    from .platform_specs import (
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        Scenario,
        ScenarioRegistry,
        SelectedUniversalUninstallScenario,
        TargetRuntimeValidationSpec,
        UniversalUninstallScenarioSpec,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry  # type: ignore[no-redef]
    from platform_specs import (  # type: ignore[no-redef]
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        Scenario,
        ScenarioRegistry,
        SelectedUniversalUninstallScenario,
        TargetRuntimeValidationSpec,
        UniversalUninstallScenarioSpec,
    )


TARGET_RUNTIME_VERIFICATION_POLICY = {
    "performed": False,
    "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
}


def _default_universal_uninstall_specs() -> tuple[UniversalUninstallScenarioSpec, ...]:
    return (
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


def _default_disposable_artifact_specs() -> tuple[DisposableArtifactScenarioSpec, ...]:
    return (
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


def _default_runtime_limitation_sections() -> tuple[TargetRuntimeValidationSpec, ...]:
    return (
        TargetRuntimeValidationSpec(
            section_title="Windows Validation",
            status="payload_consistency_only",
            evidence_path=None,
            strategy=(
                "Linux Docker validates Windows-named payload consistency only; real "
                "Windows runtime/path semantics require separate Windows validation"
            ),
            targets=(
                "windows payload file-effect simulation",
                "antigravity remapping to antigravity-windows",
                "Windows-specific skill payload and references generation",
                "payload consistency for explicit Windows platform selection",
            ),
            notes=(
                "Linux sandbox results for windows and antigravity-windows check packaged payloads, "
                "references, and generated file consistency only.",
                "This does not validate Windows Path.home(), PowerShell/cmd entrypoints, cleanup semantics, "
                "permissions, or target-app discovery.",
            ),
        ),
    )


@dataclass(frozen=True)
class HarnessPolicy:
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...] = field(default_factory=_default_universal_uninstall_specs)
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...] = field(default_factory=_default_disposable_artifact_specs)
    runtime_limitation_sections: tuple[TargetRuntimeValidationSpec, ...] = field(default_factory=_default_runtime_limitation_sections)
    target_runtime_verification: dict[str, object] = field(default_factory=lambda: dict(TARGET_RUNTIME_VERIFICATION_POLICY))

    def validate_roots(self, declared_roots: Iterable[str]) -> None:
        declared = set(declared_roots)
        unknown: set[str] = set()
        unknown.update(spec.cwd_root for spec in self.universal_uninstall_specs if spec.cwd_root not in declared)
        for spec in self.disposable_artifact_specs:
            if spec.cwd_root not in declared:
                unknown.add(spec.cwd_root)
            if spec.disposable_path_root not in declared:
                unknown.add(spec.disposable_path_root)
        if unknown:
            raise RuntimeError(f"unknown harness policy root declaration(s): {', '.join(sorted(unknown))}")


DEFAULT_HARNESS_POLICY = HarnessPolicy()


@dataclass(frozen=True, init=False)
class ValidationPlan:
    platforms: tuple[str, ...]
    requested_scope: str
    standard_scenarios: tuple[Scenario, ...]
    universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...]
    disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...]
    coverage_records: tuple[dict[str, object], ...]
    target_runtime_validation_sections: tuple[dict[str, object], ...]
    platform_coverage_summary: dict[str, object]
    target_runtime_verification: dict[str, object] = field(default_factory=lambda: dict(TARGET_RUNTIME_VERIFICATION_POLICY))

    def __init__(
        self,
        *,
        requested_scope: str,
        standard_scenarios: tuple[Scenario, ...],
        platform_coverage_summary: dict[str, object],
        platforms: tuple[str, ...] | None = None,
        selected_platforms: tuple[str, ...] | None = None,
        universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...] | None = None,
        universal_uninstall_scenarios: tuple[SelectedUniversalUninstallScenario, ...] | None = None,
        disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...] | None = None,
        disposable_artifact_scenarios: tuple[DisposableArtifactScenarioSpec, ...] | None = None,
        coverage_records: tuple[dict[str, object], ...] | None = None,
        platform_coverage: tuple[dict[str, object], ...] | None = None,
        target_runtime_validation_sections: tuple[dict[str, object], ...] | None = None,
        runtime_limitation_sections: tuple[dict[str, object], ...] | None = None,
        target_runtime_verification: dict[str, object] | None = None,
    ) -> None:
        resolved_platforms = platforms if platforms is not None else selected_platforms
        resolved_universal = universal_uninstall if universal_uninstall is not None else universal_uninstall_scenarios
        resolved_disposable = disposable_artifacts if disposable_artifacts is not None else disposable_artifact_scenarios
        resolved_coverage = coverage_records if coverage_records is not None else platform_coverage
        resolved_runtime = target_runtime_validation_sections if target_runtime_validation_sections is not None else runtime_limitation_sections
        if resolved_platforms is None:
            raise TypeError("ValidationPlan requires platforms or selected_platforms")
        if resolved_universal is None:
            raise TypeError("ValidationPlan requires universal_uninstall or universal_uninstall_scenarios")
        if resolved_disposable is None:
            raise TypeError("ValidationPlan requires disposable_artifacts or disposable_artifact_scenarios")
        if resolved_coverage is None:
            raise TypeError("ValidationPlan requires coverage_records or platform_coverage")
        if resolved_runtime is None:
            raise TypeError("ValidationPlan requires target_runtime_validation_sections or runtime_limitation_sections")
        object.__setattr__(self, "platforms", resolved_platforms)
        object.__setattr__(self, "requested_scope", requested_scope)
        object.__setattr__(self, "standard_scenarios", standard_scenarios)
        object.__setattr__(self, "universal_uninstall", resolved_universal)
        object.__setattr__(self, "disposable_artifacts", resolved_disposable)
        object.__setattr__(self, "coverage_records", resolved_coverage)
        object.__setattr__(self, "target_runtime_validation_sections", resolved_runtime)
        object.__setattr__(self, "platform_coverage_summary", platform_coverage_summary)
        object.__setattr__(
            self,
            "target_runtime_verification",
            dict(TARGET_RUNTIME_VERIFICATION_POLICY) if target_runtime_verification is None else target_runtime_verification,
        )

    @property
    def selected_platforms(self) -> tuple[str, ...]:
        return self.platforms

    @property
    def universal_uninstall_scenarios(self) -> tuple[SelectedUniversalUninstallScenario, ...]:
        return self.universal_uninstall

    @property
    def disposable_artifact_scenarios(self) -> tuple[DisposableArtifactScenarioSpec, ...]:
        return self.disposable_artifacts

    @property
    def runtime_limitation_sections(self) -> tuple[dict[str, object], ...]:
        return self.target_runtime_validation_sections

    @property
    def platform_coverage(self) -> tuple[dict[str, object], ...]:
        return self.coverage_records

    @property
    def synthetic_scenario_count(self) -> int:
        return len(self.universal_uninstall) + len(self.disposable_artifacts)

    @property
    def scenario_count(self) -> int:
        return len(self.standard_scenarios) + self.synthetic_scenario_count


def _selected_scopes(scope: str) -> tuple[str, ...]:
    if scope == "both":
        return ("user", "project")
    if scope in {"user", "project"}:
        return (scope,)
    raise RuntimeError(f"unknown sandbox scope: {scope}")


def selected_platforms(
    registry: ScenarioRegistry,
    *,
    all_platforms: bool,
    platform_name: str | None,
    selected_platform_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    if selected_platform_names is not None:
        selected = tuple(selected_platform_names)
        unknown = [name for name in selected if name not in registry.specs]
        if unknown:
            raise RuntimeError(f"unknown sandbox platform(s): {', '.join(unknown)}")
        return selected
    if all_platforms:
        return tuple(sorted(registry.specs))
    if platform_name is None or platform_name not in registry.specs:
        raise RuntimeError(f"unknown sandbox platform(s): {platform_name}")
    return (platform_name,)


def _standard_scenarios(registry: ScenarioRegistry, platforms: tuple[str, ...], scope: str) -> tuple[Scenario, ...]:
    if not hasattr(registry, "make_scenario") and hasattr(registry, "platform_scenarios"):
        return tuple(scenario for platform_name in platforms for scenario in registry.platform_scenarios(platform_name, scope))
    scenarios: list[Scenario] = []
    for platform_name in platforms:
        for one_scope in _selected_scopes(scope):
            scenario = registry.make_scenario(platform_name, one_scope)
            if scenario is not None:
                scenarios.append(scenario)
    return tuple(scenarios)


def coverage_records(registry: ScenarioRegistry, platforms: tuple[str, ...], scope: str) -> tuple[dict[str, object], ...]:
    if not hasattr(registry, "make_scenario") and hasattr(registry, "coverage_records"):
        return tuple(registry.coverage_records(list(platforms), scope))
    records: list[dict[str, object]] = []
    for platform_name in platforms:
        for one_scope in _selected_scopes(scope):
            reason = registry.unsupported_scope_reason(platform_name, one_scope)
            scenario = registry.make_scenario(platform_name, one_scope) if reason is None else None
            if scenario is None:
                records.append(
                    {
                        "platform": platform_name,
                        "scope": one_scope,
                        "status": "unsupported",
                        "reason": reason or "no sandbox scenario is defined for this platform/scope",
                    }
                )
                continue
            records.append(
                {
                    "platform": platform_name,
                    "scope": one_scope,
                    "status": "runnable",
                    "scenario_id": registry.scenario_id(platform_name, one_scope),
                    "install_command": list(scenario.install_command),
                    "uninstall_command": None if scenario.uninstall_command is None else list(scenario.uninstall_command),
                    "generic_direct_equivalence": registry.equivalence_status(scenario),
                    "risk_notes": list(scenario.risk_notes),
                }
            )
    return tuple(records)


def universal_uninstall_scenarios(
    registry: ScenarioRegistry,
    platforms: tuple[str, ...],
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[SelectedUniversalUninstallScenario, ...]:
    if not hasattr(registry, "make_scenario"):
        return ()
    specs = getattr(registry, "universal_uninstall_specs", ()) or policy.universal_uninstall_specs
    requested = set(platforms)
    selected_scopes = set(_selected_scopes(scope))
    selected: list[SelectedUniversalUninstallScenario] = []
    for universal_spec in specs:
        if universal_spec.scope not in selected_scopes:
            continue
        scenarios = [
            registry.make_scenario(platform_name, universal_spec.eligible_platform_scope)
            for platform_name in platforms
            if platform_name in requested
            and universal_spec.eligible_platform_scope in registry.platform_spec(platform_name).universal_uninstall_scopes
        ]
        runnable = tuple(scenario for scenario in scenarios if scenario is not None)
        if len(runnable) >= universal_spec.minimum_installed_scenarios:
            selected.append(SelectedUniversalUninstallScenario(universal_spec, runnable))
    return tuple(selected)


def disposable_artifact_scenarios(
    registry: ScenarioRegistry,
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[DisposableArtifactScenarioSpec, ...]:
    specs = getattr(registry, "disposable_artifact_specs", ()) or policy.disposable_artifact_specs
    return tuple(spec for spec in specs if scope in spec.scope_eligibility)


def _dedupe_sections(sections: Iterable[TargetRuntimeValidationSpec]) -> tuple[dict[str, object], ...]:
    rendered: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for section in sections:
        key = (section.section_title, section.status)
        if key in seen:
            continue
        seen.add(key)
        rendered.append(section.to_manifest())
    return tuple(rendered)


def target_runtime_validation_sections(
    registry: ScenarioRegistry,
    platforms: tuple[str, ...] | None = None,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[dict[str, object], ...]:
    if any(not hasattr(platform, "target_runtime_validation") for platform in registry.specs.values()):
        if hasattr(registry, "target_runtime_validation_sections"):
            return tuple(registry.target_runtime_validation_sections())
        return ()
    if platforms is None:
        platforms = tuple(registry.specs)
    declared_sections = [
        section
        for platform_name in platforms
        for section in registry.platform_spec(platform_name).target_runtime_validation
    ]
    policy_sections = policy.runtime_limitation_sections if any(registry.platform_spec(platform_name).simulated_linux_layout for platform_name in platforms) else ()
    return _dedupe_sections([*declared_sections, *policy_sections])


def _coverage_summary(
    *,
    platforms: tuple[str, ...],
    scope: str,
    standard_scenarios: tuple[Scenario, ...],
    universal_uninstall_scenarios: tuple[SelectedUniversalUninstallScenario, ...],
    disposable_artifact_scenarios: tuple[DisposableArtifactScenarioSpec, ...],
    coverage: tuple[dict[str, object], ...],
) -> dict[str, object]:
    unsupported = sum(1 for record in coverage if record["status"] == "unsupported")
    return {
        "registered_platform_count": len(platforms),
        "requested_scope": scope,
        "runnable_scope_count": len(standard_scenarios),
        "universal_scenario_count": len(universal_uninstall_scenarios) + len(disposable_artifact_scenarios),
        "unsupported_scope_count": unsupported,
    }


def build_validation_plan(
    registry: ScenarioRegistry,
    *,
    all_platforms: bool,
    platform_name: str | None = None,
    selected_platform_names: Iterable[str] | None = None,
    scope: str = "both",
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
    root_registry: SandboxRootRegistry = DEFAULT_SANDBOX_ROOT_REGISTRY,
) -> ValidationPlan:
    declared_roots = root_registry.declared_expected_root_names()
    if hasattr(registry, "validate_roots"):
        registry.validate_roots(declared_roots)
    policy.validate_roots(declared_roots)

    platforms = selected_platforms(
        registry,
        all_platforms=all_platforms,
        platform_name=platform_name,
        selected_platform_names=selected_platform_names,
    )
    standard = _standard_scenarios(registry, platforms, scope)
    universal = universal_uninstall_scenarios(registry, platforms, scope, policy)
    disposable = disposable_artifact_scenarios(registry, scope, policy)
    coverage = coverage_records(registry, platforms, scope)
    return ValidationPlan(
        platforms=platforms,
        requested_scope=scope,
        standard_scenarios=standard,
        universal_uninstall=universal,
        disposable_artifacts=disposable,
        coverage_records=coverage,
        target_runtime_validation_sections=target_runtime_validation_sections(registry, platforms, policy),
        platform_coverage_summary=_coverage_summary(
            platforms=platforms,
            scope=scope,
            standard_scenarios=standard,
            universal_uninstall_scenarios=universal,
            disposable_artifact_scenarios=disposable,
            coverage=coverage,
        ),
        target_runtime_verification=dict(policy.target_runtime_verification),
    )
