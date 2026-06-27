from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

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
    def selected_targets(self) -> tuple[str, ...]:
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
    registry: InstallTargetCatalog,
    *,
    all_platforms: bool,
    platform_name: str | None,
    selected_platform_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    if selected_platform_names is not None:
        selected_targets = tuple(selected_platform_names)
        unknown = [name for name in selected_targets if name not in registry.specs]
        if unknown:
            raise RuntimeError(f"unknown sandbox platform(s): {', '.join(unknown)}")
        return selected_targets
    if all_platforms:
        return tuple(sorted(registry.specs))
    if platform_name is None or platform_name not in registry.specs:
        raise RuntimeError(f"unknown sandbox platform(s): {platform_name}")
    return (platform_name,)


def _standard_scenarios(registry: InstallTargetCatalog, platforms: tuple[str, ...], scope: str) -> tuple[Scenario, ...]:
    if not hasattr(registry, "make_scenario") and hasattr(registry, "platform_scenarios"):
        return tuple(scenario for platform_name in platforms for scenario in registry.platform_scenarios(platform_name, scope))
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
    all_platforms: bool,
    platform_name: str | None = None,
    selected_platform_names: Iterable[str] | None = None,
    scope: str = "both",
    policy: HarnessPolicy = DEFAULT_HARNESS_POLICY,
    root_registry: SandboxRootRegistry = DEFAULT_SANDBOX_ROOT_REGISTRY,
) -> ValidationPlan:
    declared_roots = root_registry.install_surface_root_names()
    if hasattr(registry, "validate_target_roots"):
        registry.validate_target_roots(declared_roots)
    elif hasattr(registry, "validate_roots"):
        registry.validate_roots(declared_roots)
    validate_policy_owned_roots(registry, policy, declared_roots)

    selected_targets = selected_platforms(
        registry,
        all_platforms=all_platforms,
        platform_name=platform_name,
        selected_platform_names=selected_platform_names,
    )
    standard = _standard_scenarios(registry, selected_targets, scope)
    universal = universal_uninstall_scenarios(registry, selected_targets, scope, policy)
    disposable = disposable_artifact_scenarios(registry, scope, policy)
    coverage = coverage_records(registry, selected_targets, scope)
    return ValidationPlan(
        platforms=selected_targets,
        requested_scope=scope,
        standard_scenarios=standard,
        universal_uninstall=universal,
        disposable_artifacts=disposable,
        coverage_records=coverage,
        target_runtime_validation_sections=target_runtime_validation_sections(registry, selected_targets, policy),
        platform_coverage_summary=_coverage_summary(
            platforms=selected_targets,
            scope=scope,
            standard_scenarios=standard,
            universal_uninstall_scenarios=universal,
            disposable_artifact_scenarios=disposable,
            coverage=coverage,
        ),
        target_runtime_verification=dict(policy.target_runtime_verification),
    )
