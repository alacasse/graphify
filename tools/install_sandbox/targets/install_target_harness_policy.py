from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

try:
    from . import install_target_selection as _selection
    from .install_target_models import (
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        TargetRuntimeValidationSpec,
        UniversalUninstallScenarioSpec,
    )
    from .install_target_scenarios import _dedupe_notes
except ImportError:  # pragma: no cover - direct script import fallback
    from targets import install_target_selection as _selection  # type: ignore[no-redef]
    from targets.install_target_models import (  # type: ignore[no-redef]
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        TargetRuntimeValidationSpec,
        UniversalUninstallScenarioSpec,
    )
    from targets.install_target_scenarios import _dedupe_notes  # type: ignore[no-redef]


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
        validate_harness_policy_roots(self, declared_roots)


DEFAULT_HARNESS_POLICY = HarnessPolicy()


def universal_uninstall_spec_for_scope(
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    scope: str,
) -> UniversalUninstallScenarioSpec | None:
    return next((spec for spec in universal_uninstall_specs if spec.scope == scope), None)


def universal_uninstall_scenario_id(
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    scope: str,
) -> str:
    spec = universal_uninstall_spec_for_scope(universal_uninstall_specs, scope)
    return spec.scenario_id if spec is not None else f"universal-uninstall-{scope}"


def purge_disposable_graphify_out_scenario_id(
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...],
) -> str:
    for spec in disposable_artifact_specs:
        if spec.disposable_path_relative == "graphify-out":
            return spec.scenario_id
    return "purge-disposable-graphify-out"


def universal_uninstall_scenarios(
    specs: dict[str, PlatformSpec],
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    target_names: list[str],
    scope: str,
) -> list[SelectedUniversalUninstallScenario]:
    requested = set(target_names)
    ordered_targets = tuple(target_name for target_name in specs if target_name in requested)
    return list(
        _select_universal_uninstall_scenarios(
            universal_uninstall_specs,
            ordered_targets,
            scope,
            target_spec_for=lambda target_name: specs[target_name],
            make_scenario=lambda target_name, scenario_scope: _selection.make_scenario(
                specs,
                target_name,
                scenario_scope,
            ),
        )
    )


def universal_uninstall_groups(
    specs: dict[str, PlatformSpec],
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    target_names: list[str],
    scope: str,
) -> list[tuple[str, list[Scenario]]]:
    return [
        (selected.spec.scope, list(selected.installed_scenarios))
        for selected in universal_uninstall_scenarios(specs, universal_uninstall_specs, target_names, scope)
    ]


def disposable_artifact_scenarios(
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...],
    scope: str,
) -> list[DisposableArtifactScenarioSpec]:
    return [spec for spec in disposable_artifact_specs if scope in spec.scope_eligibility]


def selected_universal_uninstall_scenarios(
    registry: object,
    target_names: tuple[str, ...],
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[SelectedUniversalUninstallScenario, ...]:
    if not hasattr(registry, "make_scenario"):
        return ()
    specs = getattr(registry, "universal_uninstall_specs", ()) or policy.universal_uninstall_specs
    return _select_universal_uninstall_scenarios(
        specs,
        target_names,
        scope,
        target_spec_for=registry.target_spec,
        make_scenario=registry.make_scenario,
    )


def _select_universal_uninstall_scenarios(
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    target_names: Iterable[str],
    scope: str,
    *,
    target_spec_for: Callable[[str], PlatformSpec],
    make_scenario: Callable[[str, str], Scenario | None],
) -> tuple[SelectedUniversalUninstallScenario, ...]:
    selected_scopes = set(_selection.selected_scopes(scope))
    selected: list[SelectedUniversalUninstallScenario] = []
    for universal_spec in universal_uninstall_specs:
        if universal_spec.scope not in selected_scopes:
            continue
        scenarios = [
            make_scenario(target_name, universal_spec.eligible_platform_scope)
            for target_name in target_names
            if universal_spec.eligible_platform_scope in target_spec_for(target_name).universal_uninstall_scopes
        ]
        runnable = tuple(scenario for scenario in scenarios if scenario is not None)
        if len(runnable) >= universal_spec.minimum_installed_scenarios:
            selected.append(SelectedUniversalUninstallScenario(universal_spec, runnable))
    return tuple(selected)


def selected_disposable_artifact_scenarios(
    registry: object,
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[DisposableArtifactScenarioSpec, ...]:
    specs = getattr(registry, "disposable_artifact_specs", ()) or policy.disposable_artifact_specs
    return tuple(disposable_artifact_scenarios(specs, scope))


def validate_selected_harness_policy_roots(
    registry: object,
    policy: HarnessPolicy,
    declared_roots: Iterable[str],
) -> None:
    selected_policy = HarnessPolicy(
        universal_uninstall_specs=getattr(registry, "universal_uninstall_specs", ()) or policy.universal_uninstall_specs,
        disposable_artifact_specs=getattr(registry, "disposable_artifact_specs", ()) or policy.disposable_artifact_specs,
        runtime_limitation_sections=policy.runtime_limitation_sections,
        target_runtime_verification=policy.target_runtime_verification,
    )
    selected_policy.validate_roots(declared_roots)


def target_runtime_validation_sections(specs: dict[str, PlatformSpec]) -> list[dict[str, object]]:
    return _dedupe_runtime_sections(
        validation
        for platform in specs.values()
        for validation in platform.target_runtime_validation
    )


def selected_target_runtime_validation_sections(
    registry: object,
    target_names: tuple[str, ...] | None = None,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[dict[str, object], ...]:
    specs = getattr(registry, "specs")
    if any(not hasattr(platform, "target_runtime_validation") for platform in specs.values()):
        if hasattr(registry, "target_runtime_validation_sections"):
            return tuple(registry.target_runtime_validation_sections())
        return ()
    if target_names is None:
        target_names = tuple(specs)
    selected = [registry.target_spec(target_name) for target_name in target_names]
    declared_sections = [section for platform in selected for section in platform.target_runtime_validation]
    policy_sections = policy.runtime_limitation_sections if any(platform.simulated_linux_layout for platform in selected) else ()
    return tuple(_dedupe_runtime_sections([*declared_sections, *policy_sections]))


def _dedupe_runtime_sections(section_specs: Iterable[TargetRuntimeValidationSpec]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for validation in section_specs:
        key = (validation.section_title, validation.status)
        if key in seen:
            continue
        seen.add(key)
        sections.append(validation.to_manifest())
    return sections


def validate_harness_policy_roots(policy: HarnessPolicy, declared_roots: Iterable[str]) -> None:
    declared = set(declared_roots)
    unknown: set[str] = set()
    unknown.update(spec.cwd_root for spec in policy.universal_uninstall_specs if spec.cwd_root not in declared)
    for spec in policy.disposable_artifact_specs:
        if spec.cwd_root not in declared:
            unknown.add(spec.cwd_root)
        if spec.disposable_path_root not in declared:
            unknown.add(spec.disposable_path_root)
    if unknown:
        raise RuntimeError(f"unknown harness policy root declaration(s): {', '.join(sorted(unknown))}")


def validate_roots(
    specs: dict[str, PlatformSpec],
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...],
    declared_roots: set[str],
) -> None:
    unknown: set[str] = set()
    for platform in specs.values():
        for scope in platform.scopes.values():
            if scope.cwd_root not in declared_roots:
                unknown.add(scope.cwd_root)
            unknown.update(entry.root for entry in scope.expected if entry.root not in declared_roots)
    unknown.update(spec.cwd_root for spec in universal_uninstall_specs if spec.cwd_root not in declared_roots)
    for spec in disposable_artifact_specs:
        if spec.cwd_root not in declared_roots:
            unknown.add(spec.cwd_root)
        if spec.disposable_path_root not in declared_roots:
            unknown.add(spec.disposable_path_root)
    if unknown:
        raise RuntimeError(f"unknown sandbox root declaration(s): {', '.join(sorted(unknown))}")


def risk_notes(
    specs: dict[str, PlatformSpec],
    *notes: str,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    ordered = list(notes)
    spec = specs.get(platform_name or "")
    if spec is not None and spec.simulated_linux_layout:
        ordered.append(SIMULATED_LINUX_LAYOUT_NOTE)
    return _dedupe_notes(*ordered)
