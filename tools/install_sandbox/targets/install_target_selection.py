from __future__ import annotations

import re

try:
    from .install_target_models import InstallCommandVariant, InstallSurface, PlatformSpec, Scenario
    from .install_target_scenarios import _generic_install_command, _skill
except ImportError:  # pragma: no cover - direct script import fallback
    from targets.install_target_models import InstallCommandVariant, InstallSurface, PlatformSpec, Scenario  # type: ignore[no-redef]
    from targets.install_target_scenarios import _generic_install_command, _skill  # type: ignore[no-redef]


def selected_scopes(scope: str) -> list[str]:
    return ["user", "project"] if scope == "both" else [scope]


def target_spec(specs: dict[str, PlatformSpec], target_name: str) -> PlatformSpec:
    try:
        return specs[target_name]
    except KeyError as exc:
        raise RuntimeError(f"unknown sandbox platform: {target_name}") from exc


def selected_targets(specs: dict[str, PlatformSpec], *, all_platforms: bool, target_name: str | None) -> list[str]:
    targets = list(specs) if all_platforms else [target_name]
    unknown = [name for name in targets if name not in specs]
    if unknown:
        raise RuntimeError(f"unknown sandbox platform(s): {', '.join(str(name) for name in unknown)}")
    return [str(name) for name in targets]


def user_skill(specs: dict[str, PlatformSpec], platform_name: str) -> InstallSurface:
    skill = target_spec(specs, platform_name).user_skill
    if skill is None:
        raise RuntimeError(f"sandbox platform has no user skill path: {platform_name}")
    return _skill("home", skill)


def project_skill(specs: dict[str, PlatformSpec], platform_name: str) -> InstallSurface:
    skill = target_spec(specs, platform_name).project_skill
    if skill is None:
        raise RuntimeError(f"sandbox platform has no project skill path: {platform_name}")
    return _skill("project", skill)


def unsupported_scope_reason(specs: dict[str, PlatformSpec], platform_name: str, scope: str) -> str | None:
    return target_spec(specs, platform_name).unsupported_scopes.get(scope)


def direct_uninstall_command(specs: dict[str, PlatformSpec], platform_name: str) -> tuple[str, ...] | None:
    scope = target_spec(specs, platform_name).scopes.get("user")
    return None if scope is None else scope.uninstall_command


def generic_install_command(platform_name: str, scope: str) -> tuple[str, ...]:
    return _generic_install_command(platform_name, scope)


def install_variants_for_scope(
    specs: dict[str, PlatformSpec],
    platform_name: str,
    scope: str,
) -> tuple[InstallCommandVariant, ...]:
    scope_spec = target_spec(specs, platform_name).scopes.get(scope)
    if scope_spec is None:
        return ()
    if scope_spec.install_variants:
        return scope_spec.install_variants
    variants = [InstallCommandVariant("primary", scope_spec.install_command)]
    if scope_spec.equivalent_install_command is not None:
        variants.append(InstallCommandVariant("alternate", scope_spec.equivalent_install_command))
    return tuple(variants)


def install_variants(specs: dict[str, PlatformSpec], scenario: Scenario) -> tuple[InstallCommandVariant, ...]:
    return install_variants_for_scope(specs, scenario.platform, scenario.scope)


def direct_install_command(specs: dict[str, PlatformSpec], platform_name: str, scope: str) -> tuple[str, ...] | None:
    scope_spec = target_spec(specs, platform_name).scopes.get(scope)
    if scope_spec is None:
        return None
    for variant in install_variants_for_scope(specs, platform_name, scope):
        if variant.label == "direct":
            return variant.command
    return None


def make_scenario(specs: dict[str, PlatformSpec], platform_name: str, scope: str) -> Scenario | None:
    spec = target_spec(specs, platform_name)
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


def target_scenarios(specs: dict[str, PlatformSpec], target_name: str, scope: str) -> list[Scenario]:
    target_spec(specs, target_name)
    return [
        scenario
        for one_scope in selected_scopes(scope)
        if (scenario := make_scenario(specs, target_name, one_scope)) is not None
    ]


def equivalent_install_command(specs: dict[str, PlatformSpec], scenario: Scenario) -> tuple[str, ...] | None:
    variants = install_variants(specs, scenario)
    if len(variants) < 2:
        return None
    for variant in variants:
        if scenario.install_command == variant.command:
            return next((candidate.command for candidate in variants if candidate.command != variant.command), None)
    return None


def equivalent_install_variants(
    specs: dict[str, PlatformSpec],
    scenario: Scenario,
) -> tuple[InstallCommandVariant, InstallCommandVariant] | None:
    variants = install_variants(specs, scenario)
    if len(variants) < 2:
        return None
    primary = next((variant for variant in variants if variant.command == scenario.install_command), variants[0])
    alternate = next((variant for variant in variants if variant.command != primary.command), None)
    if alternate is None:
        return None
    return primary, alternate


def equivalence_status(specs: dict[str, PlatformSpec], scenario: Scenario) -> dict[str, object]:
    equivalent = equivalent_install_command(specs, scenario)
    if equivalent is not None:
        return {"status": "runnable", "command": list(equivalent)}
    return {
        "status": "not_applicable",
        "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
    }


def scenario_id(platform_name: str, scope: str) -> str:
    raw = f"{platform_name}-{scope}".lower()
    safe = re.sub(r"[^a-z0-9_.-]+", "-", raw)
    safe = re.sub(r"[-_.]{2,}", "-", safe).strip(".-_")
    return safe or "scenario"


def coverage_records(specs: dict[str, PlatformSpec], platforms: list[str], scope: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for platform_name in platforms:
        for one_scope in selected_scopes(scope):
            reason = unsupported_scope_reason(specs, platform_name, one_scope)
            scenario = make_scenario(specs, platform_name, one_scope) if reason is None else None
            if scenario is not None:
                records.append(
                    {
                        "platform": platform_name,
                        "scope": one_scope,
                        "status": "runnable",
                        "scenario_id": scenario_id(platform_name, one_scope),
                        "install_command": list(scenario.install_command),
                        "uninstall_command": None if scenario.uninstall_command is None else list(scenario.uninstall_command),
                        "generic_direct_equivalence": equivalence_status(specs, scenario),
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
