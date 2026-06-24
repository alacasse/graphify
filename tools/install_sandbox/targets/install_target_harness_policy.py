from __future__ import annotations

try:
    from . import install_target_selection as _selection
    from .install_target_models import (
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        UniversalUninstallScenarioSpec,
    )
    from .install_target_scenarios import _dedupe_notes
except ImportError:  # pragma: no cover - direct script import fallback
    from targets import install_target_selection as _selection  # type: ignore[no-redef]
    from targets.install_target_models import (  # type: ignore[no-redef]
        SIMULATED_LINUX_LAYOUT_NOTE,
        DisposableArtifactScenarioSpec,
        PlatformSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
        UniversalUninstallScenarioSpec,
    )
    from targets.install_target_scenarios import _dedupe_notes  # type: ignore[no-redef]


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
    platforms: list[str],
    scope: str,
) -> list[SelectedUniversalUninstallScenario]:
    requested = set(platforms)
    selected_scopes = set(_selection.selected_scopes(scope))
    selected: list[SelectedUniversalUninstallScenario] = []
    for universal_spec in universal_uninstall_specs:
        if universal_spec.scope not in selected_scopes:
            continue
        scenarios = [
            _selection.make_scenario(specs, platform_name, universal_spec.eligible_platform_scope)
            for platform_name, spec in specs.items()
            if platform_name in requested and universal_spec.eligible_platform_scope in spec.universal_uninstall_scopes
        ]
        runnable = tuple(scenario for scenario in scenarios if scenario is not None)
        if len(runnable) >= universal_spec.minimum_installed_scenarios:
            selected.append(SelectedUniversalUninstallScenario(universal_spec, runnable))
    return selected


def universal_uninstall_groups(
    specs: dict[str, PlatformSpec],
    universal_uninstall_specs: tuple[UniversalUninstallScenarioSpec, ...],
    platforms: list[str],
    scope: str,
) -> list[tuple[str, list[Scenario]]]:
    return [
        (selected.spec.scope, list(selected.installed_scenarios))
        for selected in universal_uninstall_scenarios(specs, universal_uninstall_specs, platforms, scope)
    ]


def disposable_artifact_scenarios(
    disposable_artifact_specs: tuple[DisposableArtifactScenarioSpec, ...],
    scope: str,
) -> list[DisposableArtifactScenarioSpec]:
    return [spec for spec in disposable_artifact_specs if scope in spec.scope_eligibility]


def target_runtime_validation_sections(specs: dict[str, PlatformSpec]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for platform in specs.values():
        for validation in platform.target_runtime_validation:
            key = (validation.section_title, validation.status)
            if key in seen:
                continue
            seen.add(key)
            sections.append(validation.to_manifest())
    return sections


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
