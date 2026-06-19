from __future__ import annotations

from typing import Literal

try:
    from .install_target_models import (
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        InstallCommandVariant,
        InstallSurface,
        ScopeSpec,
        SkillEffect,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from install_target_models import (  # type: ignore[no-redef]
        MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
        MIXED_SCOPE_PROJECT_WIRING_NOTE,
        InstallCommandVariant,
        InstallSurface,
        ScopeSpec,
        SkillEffect,
    )


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
