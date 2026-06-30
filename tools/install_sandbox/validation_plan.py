from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

try:
    from .harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry
    from .targets.install_target_catalog import InstallTargetCatalog
    from .targets import install_target_harness_policy as _harness_policy
    from .targets.install_target_models import (
        DisposableArtifactScenarioSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry  # type: ignore[no-redef]
    from targets.install_target_catalog import InstallTargetCatalog  # type: ignore[no-redef]
    from targets import install_target_harness_policy as _harness_policy  # type: ignore[no-redef]
    from targets.install_target_models import (  # type: ignore[no-redef]
        DisposableArtifactScenarioSpec,
        Scenario,
        SelectedUniversalUninstallScenario,
    )


TARGET_RUNTIME_VERIFICATION_POLICY = _harness_policy.TARGET_RUNTIME_VERIFICATION_POLICY
HarnessPolicy = _harness_policy.HarnessPolicy
DEFAULT_HARNESS_POLICY = _harness_policy.DEFAULT_HARNESS_POLICY


ValidationWorkItemKind = Literal["standard_scenario", "universal_uninstall", "disposable_artifact"]
ValidationWorkItemPayload = Scenario | SelectedUniversalUninstallScenario | DisposableArtifactScenarioSpec


@dataclass(frozen=True)
class ValidationWorkItem:
    kind: ValidationWorkItemKind
    payload: ValidationWorkItemPayload


def _validation_work_items(
    *,
    standard_scenarios: tuple[Scenario, ...],
    universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...],
    disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...],
) -> tuple[ValidationWorkItem, ...]:
    return (
        *(ValidationWorkItem("standard_scenario", scenario) for scenario in standard_scenarios),
        *(ValidationWorkItem("universal_uninstall", selected) for selected in universal_uninstall),
        *(ValidationWorkItem("disposable_artifact", spec) for spec in disposable_artifacts),
    )


@dataclass(frozen=True, init=False)
class ValidationPlan:
    selected_target_names: tuple[str, ...]
    requested_scope: str
    standard_scenarios: tuple[Scenario, ...]
    universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...]
    disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...]
    validation_work_items: tuple[ValidationWorkItem, ...]
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
        selected_targets: tuple[str, ...] | None = None,
        universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...] | None = None,
        disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...] | None = None,
        coverage_records: tuple[dict[str, object], ...] | None = None,
        target_runtime_validation_sections: tuple[dict[str, object], ...] | None = None,
        target_runtime_verification: dict[str, object] | None = None,
    ) -> None:
        if selected_targets is None:
            raise TypeError("ValidationPlan requires selected_targets")
        if universal_uninstall is None:
            raise TypeError("ValidationPlan requires universal_uninstall")
        if disposable_artifacts is None:
            raise TypeError("ValidationPlan requires disposable_artifacts")
        if coverage_records is None:
            raise TypeError("ValidationPlan requires coverage_records")
        if target_runtime_validation_sections is None:
            raise TypeError("ValidationPlan requires target_runtime_validation_sections")
        object.__setattr__(self, "selected_target_names", selected_targets)
        object.__setattr__(self, "requested_scope", requested_scope)
        object.__setattr__(self, "standard_scenarios", standard_scenarios)
        object.__setattr__(self, "universal_uninstall", universal_uninstall)
        object.__setattr__(self, "disposable_artifacts", disposable_artifacts)
        object.__setattr__(
            self,
            "validation_work_items",
            _validation_work_items(
                standard_scenarios=standard_scenarios,
                universal_uninstall=universal_uninstall,
                disposable_artifacts=disposable_artifacts,
            ),
        )
        object.__setattr__(self, "coverage_records", coverage_records)
        object.__setattr__(self, "target_runtime_validation_sections", target_runtime_validation_sections)
        object.__setattr__(self, "platform_coverage_summary", platform_coverage_summary)
        object.__setattr__(
            self,
            "target_runtime_verification",
            dict(TARGET_RUNTIME_VERIFICATION_POLICY) if target_runtime_verification is None else target_runtime_verification,
        )

    @property
    def selected_targets(self) -> tuple[str, ...]:
        return self.selected_target_names

    @property
    def synthetic_scenario_count(self) -> int:
        return len(self.universal_uninstall) + len(self.disposable_artifacts)

    @property
    def standard_validation_count(self) -> int:
        return sum(1 for work_item in self.validation_work_items if work_item.kind == "standard_scenario")

    @property
    def scenario_count(self) -> int:
        return self.standard_validation_count + self.synthetic_scenario_count


def _selected_scopes(scope: str) -> tuple[str, ...]:
    if scope == "both":
        return ("user", "project")
    if scope in {"user", "project"}:
        return (scope,)
    raise RuntimeError(f"unknown sandbox scope: {scope}")


def selected_targets(
    registry: InstallTargetCatalog,
    *,
    all_targets: bool,
    target_name: str | None,
    selected_target_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    if selected_target_names is not None:
        targets = tuple(selected_target_names)
        unknown = [name for name in targets if name not in registry.specs]
        if unknown:
            raise RuntimeError(f"unknown sandbox platform(s): {', '.join(unknown)}")
        return targets
    if all_targets:
        return tuple(sorted(registry.specs))
    if target_name is None or target_name not in registry.specs:
        raise RuntimeError(f"unknown sandbox platform(s): {target_name}")
    return (target_name,)


def _standard_scenarios(registry: InstallTargetCatalog, platforms: tuple[str, ...], scope: str) -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    for platform_name in platforms:
        for one_scope in _selected_scopes(scope):
            scenario = registry.make_scenario(platform_name, one_scope)
            if scenario is not None:
                scenarios.append(scenario)
    return tuple(scenarios)


def coverage_records(registry: InstallTargetCatalog, platforms: tuple[str, ...], scope: str) -> tuple[dict[str, object], ...]:
    return tuple(registry.coverage_records(list(platforms), scope))


def universal_uninstall_scenarios(
    registry: InstallTargetCatalog,
    platforms: tuple[str, ...],
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[SelectedUniversalUninstallScenario, ...]:
    return _harness_policy.selected_universal_uninstall_scenarios(registry, platforms, scope, policy)


def disposable_artifact_scenarios(
    registry: InstallTargetCatalog,
    scope: str,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[DisposableArtifactScenarioSpec, ...]:
    return _harness_policy.selected_disposable_artifact_scenarios(registry, scope, policy)


def target_runtime_validation_sections(
    registry: InstallTargetCatalog,
    platforms: tuple[str, ...] | None = None,
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
) -> tuple[dict[str, object], ...]:
    return _harness_policy.selected_target_runtime_validation_sections(registry, platforms, policy)


def validate_policy_owned_roots(
    registry: InstallTargetCatalog,
    policy: HarnessPolicy,
    declared_roots: Iterable[str],
) -> None:
    _harness_policy.validate_selected_harness_policy_roots(registry, policy, declared_roots)


def _target_fact_root_names(root_registry: SandboxRootRegistry) -> set[str]:
    return root_registry.install_surface_root_names()


def _selected_policy_root_names(root_registry: SandboxRootRegistry) -> set[str]:
    return root_registry.install_surface_root_names()


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
    registry: InstallTargetCatalog,
    *,
    all_targets: bool | None = None,
    target_name: str | None = None,
    selected_target_names: Iterable[str] | None = None,
    scope: str = "both",
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
    root_registry: SandboxRootRegistry = DEFAULT_SANDBOX_ROOT_REGISTRY,
) -> ValidationPlan:
    declared_roots = _target_fact_root_names(root_registry)
    if hasattr(registry, "validate_target_roots"):
        registry.validate_target_roots(declared_roots)
    elif hasattr(registry, "validate_roots"):
        registry.validate_roots(declared_roots)
    validate_policy_owned_roots(registry, policy, _selected_policy_root_names(root_registry))

    if all_targets is None:
        raise TypeError("build_validation_plan requires all_targets")

    selected_target_names_tuple = selected_targets(
        registry,
        all_targets=all_targets,
        target_name=target_name,
        selected_target_names=selected_target_names,
    )
    standard = _standard_scenarios(registry, selected_target_names_tuple, scope)
    universal = universal_uninstall_scenarios(registry, selected_target_names_tuple, scope, policy)
    disposable = disposable_artifact_scenarios(registry, scope, policy)
    coverage = coverage_records(registry, selected_target_names_tuple, scope)
    return ValidationPlan(
        selected_targets=selected_target_names_tuple,
        requested_scope=scope,
        standard_scenarios=standard,
        universal_uninstall=universal,
        disposable_artifacts=disposable,
        coverage_records=coverage,
        target_runtime_validation_sections=target_runtime_validation_sections(registry, selected_target_names_tuple, policy),
        platform_coverage_summary=_coverage_summary(
            platforms=selected_target_names_tuple,
            scope=scope,
            standard_scenarios=standard,
            universal_uninstall_scenarios=universal,
            disposable_artifact_scenarios=disposable,
            coverage=coverage,
        ),
        target_runtime_verification=dict(policy.target_runtime_verification),
    )
