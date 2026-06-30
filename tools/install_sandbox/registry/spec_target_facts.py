from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from ..harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
from ..surfaces.install_surface_models import InstallSurface
from ..targets.install_target_models import (
    MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
    MIXED_SCOPE_PROJECT_WIRING_NOTE,
    PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
    SIMULATED_LINUX_LAYOUT_NOTE,
    GeneratedFileExpectation,
    InstallCommandVariant,
    InstallTargetSpec,
    ReferenceBundle,
    ScopeSpec,
    TargetRuntimeValidationSpec,
)
from ..targets.install_target_scenarios import _scenario
from .spec_install_surfaces import SpecInstallSurfaceError, derive_scope_install_surfaces


_SCOPE_NAMES = {"user", "project"}
_WIDENED_SCOPE_ROOTS = ("home", "project", "user_cwd")
_KNOWN_SCOPE_RISK_NOTES = {
    PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
    MIXED_SCOPE_PROJECT_WIRING_NOTE,
    MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
    SIMULATED_LINUX_LAYOUT_NOTE,
}


class SpecTargetFactError(ValueError):
    pass


def _fail(context: str, message: str) -> None:
    raise SpecTargetFactError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


def _sequence(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(context, "expected list")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(context, "expected non-empty string")
    return value


def _bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        _fail(context, "expected boolean")
    return value


def _int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(context, "expected integer")
    return value


def _string_list(value: object, context: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _sequence(value, context)
    if not allow_empty and not items:
        _fail(context, "expected non-empty list")
    return tuple(_string(item, f"{context}[{index}]") for index, item in enumerate(items))


def _command(value: object, context: str) -> tuple[str, ...]:
    return _string_list(value, context, allow_empty=False)


def _optional_command(value: object, context: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _command(value, context)


def _validate_cwd_root(root: str, context: str) -> None:
    if root not in DEFAULT_SANDBOX_ROOT_REGISTRY.policy_cwd_root_names():
        _fail(context, f"unknown cwd root: {root}")


def _install_variants(value: object, context: str) -> tuple[InstallCommandVariant, ...]:
    variants = _sequence(value, context)
    labels: set[str] = set()
    parsed: list[InstallCommandVariant] = []
    for index, variant_value in enumerate(variants):
        variant = _mapping(variant_value, f"{context}[{index}]")
        label = _string(variant.get("label"), f"{context}[{index}].label")
        if label in labels:
            _fail(f"{context}[{index}].label", f"duplicate install variant label: {label}")
        labels.add(label)
        parsed.append(InstallCommandVariant(label, _command(variant.get("command"), f"{context}[{index}].command")))
    return tuple(parsed)


def _generated_file_expectation(value: object, context: str) -> GeneratedFileExpectation:
    data = _mapping(value, context)
    return GeneratedFileExpectation(
        relative_substrings=_string_list(data.get("relative_substrings", ["graphify"]), f"{context}.relative_substrings"),
        text_suffixes=_string_list(data.get("text_suffixes", [".json", ".js", ".md", ".mdc", ".txt", ""]), f"{context}.text_suffixes"),
        content_markers=_string_list(data.get("content_markers", ["graphify"]), f"{context}.content_markers"),
        include_user_content_sentinel=_bool(data.get("include_user_content_sentinel", True), f"{context}.include_user_content_sentinel"),
        max_text_bytes=_int(data.get("max_text_bytes", 1024 * 1024), f"{context}.max_text_bytes"),
    )


def _dedupe(items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _scope_locality(scope_name: str, expected: tuple[InstallSurface, ...]) -> tuple[str | None, tuple[str, ...]]:
    roots = {entry.root for entry in expected}
    if scope_name == "project":
        if roots <= {"project"}:
            return None, ("project",)
        return MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE, _WIDENED_SCOPE_ROOTS
    if roots <= {"home"}:
        return None, ("home",)
    return MIXED_SCOPE_PROJECT_WIRING_NOTE, _WIDENED_SCOPE_ROOTS


def _scope_risk_notes(
    explicit_notes: tuple[str, ...],
    locality_note: str | None,
    *,
    simulated_linux_layout: bool,
    lacks_user_uninstall: bool,
) -> tuple[str, ...]:
    notes: tuple[str, ...] = explicit_notes
    if lacks_user_uninstall:
        notes = (PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE, *notes)
    if locality_note is not None:
        notes = (locality_note, *notes)
    if simulated_linux_layout:
        notes = (*notes, SIMULATED_LINUX_LAYOUT_NOTE)
    return _dedupe(notes)


def _generic_install_command(platform_name: str, scope_name: str) -> tuple[str, ...]:
    if scope_name == "project":
        return ("graphify", "install", "--project", "--platform", platform_name)
    return ("graphify", "install", "--platform", platform_name)


def _direct_project_install_command(platform_name: str) -> tuple[str, ...]:
    return ("graphify", platform_name, "install", "--project")


def _scope_spec(platform_name: str, scope_name: str, value: object, context: str, *, simulated_linux_layout: bool) -> ScopeSpec:
    data = _mapping(value, context)
    if scope_name not in _SCOPE_NAMES:
        _fail(context, f"invalid platform scope: {scope_name}")
    try:
        install_surfaces = derive_scope_install_surfaces(data, context)
    except SpecInstallSurfaceError as exc:
        raise SpecTargetFactError(str(exc)) from exc
    explicit_risk_notes = _string_list(data.get("risk_notes", []), f"{context}.risk_notes")
    for note in explicit_risk_notes:
        if note not in _KNOWN_SCOPE_RISK_NOTES:
            _fail(f"{context}.risk_notes", f"unknown structured risk note: {note}")
    locality_note, derived_allowed_roots = _scope_locality(scope_name, install_surfaces)

    transitional_install_command = None
    if "install_command" in data:
        transitional_install_command = _command(data.get("install_command"), f"{context}.install_command")
    transitional_uninstall_command: tuple[str, ...] | None | str
    if "uninstall_command" in data:
        transitional_uninstall_command = _optional_command(data.get("uninstall_command"), f"{context}.uninstall_command")
    else:
        transitional_uninstall_command = "generic"
    lacks_user_uninstall = scope_name == "user" and transitional_uninstall_command is None
    risk_notes = _scope_risk_notes(
        explicit_risk_notes,
        locality_note,
        simulated_linux_layout=simulated_linux_layout,
        lacks_user_uninstall=lacks_user_uninstall,
    )
    transitional_cwd_root = None
    if "cwd_root" in data:
        transitional_cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
        _validate_cwd_root(transitional_cwd_root, f"{context}.cwd_root")
    transitional_equivalent_install_command = None
    if "equivalent_install_command" in data:
        transitional_equivalent_install_command = _optional_command(
            data.get("equivalent_install_command"),
            f"{context}.equivalent_install_command",
        )
    elif scope_name == "project" and (
        transitional_install_command is None or transitional_install_command == _generic_install_command(platform_name, scope_name)
    ):
        transitional_equivalent_install_command = _direct_project_install_command(platform_name)

    scope = _scenario(
        platform_name,
        scope_name,
        install_surfaces,
        install_command=transitional_install_command,
        uninstall_command=transitional_uninstall_command,
        cwd_root=transitional_cwd_root,
        risk_notes=risk_notes,
        equivalent_install_command=transitional_equivalent_install_command,
    )
    scope = replace(scope, allowed_roots=derived_allowed_roots)
    if "install_variants" in data:
        scope = replace(scope, install_variants=_install_variants(data.get("install_variants"), f"{context}.install_variants"))
    if "allowed_roots" in data:
        transitional_allowed_roots = _string_list(data.get("allowed_roots"), f"{context}.allowed_roots")
        for root in transitional_allowed_roots:
            _validate_cwd_root(root, f"{context}.allowed_roots")
        scope = replace(scope, allowed_roots=transitional_allowed_roots)
    if "generated_file_expectation" in data:
        scope = replace(
            scope,
            generated_file_expectation=_generated_file_expectation(
                data.get("generated_file_expectation"),
                f"{context}.generated_file_expectation",
            ),
        )
    return scope


def _reference_bundle(value: object, context: str) -> ReferenceBundle:
    if isinstance(value, str):
        return ReferenceBundle(value)
    data = _mapping(value, context)
    required = data.get("required_package_relative")
    return ReferenceBundle(
        _string(data.get("name"), f"{context}.name"),
        required_package_relative=None if required is None else _string(required, f"{context}.required_package_relative"),
    )


def _runtime_validation(value: object, context: str) -> TargetRuntimeValidationSpec:
    data = _mapping(value, context)
    evidence = data.get("evidence_path")
    return TargetRuntimeValidationSpec(
        section_title=_string(data.get("section_title"), f"{context}.section_title"),
        status=_string(data.get("status"), f"{context}.status"),
        strategy=_string(data.get("strategy"), f"{context}.strategy"),
        targets=_string_list(data.get("targets"), f"{context}.targets", allow_empty=False),
        notes=_string_list(data.get("notes"), f"{context}.notes", allow_empty=False),
        evidence_path=None if evidence is None else _string(evidence, f"{context}.evidence_path"),
    )


def _platform_runtime_validations(data: Mapping[str, Any], context: str) -> tuple[TargetRuntimeValidationSpec, ...]:
    return tuple(
        _runtime_validation(validation, f"{context}.target_runtime_validation[{index}]")
        for index, validation in enumerate(_sequence(data.get("target_runtime_validation", []), f"{context}.target_runtime_validation"))
    )


def target_spec(platform_key: str, value: object, context: str) -> InstallTargetSpec:
    data = _mapping(value, context)
    name = platform_key
    if "name" in data:
        name = _string(data.get("name"), f"{context}.name")
        if name != platform_key:
            _fail(f"{context}.name", f"platform key/name mismatch: {platform_key} != {name}")

    scopes_value = _mapping(data.get("scopes", {}), f"{context}.scopes")
    unsupported_value = _mapping(data.get("unsupported_scopes", {}), f"{context}.unsupported_scopes")
    for scope_name in (*scopes_value, *unsupported_value):
        if scope_name not in _SCOPE_NAMES:
            _fail(context, f"invalid platform scope: {scope_name}")
    for scope_name in sorted(_SCOPE_NAMES):
        runnable = scope_name in scopes_value
        unsupported = scope_name in unsupported_value
        if runnable == unsupported:
            _fail(f"{context}.{scope_name}", "expected exactly one runnable scope or unsupported reason")

    simulated_linux_layout = _bool(data.get("simulated_linux_layout", False), f"{context}.simulated_linux_layout")
    scopes = {
        scope_name: _scope_spec(platform_key, scope_name, scope_value, f"{context}.scopes.{scope_name}", simulated_linux_layout=simulated_linux_layout)
        for scope_name, scope_value in scopes_value.items()
    }
    unsupported_scopes = {
        scope_name: _string(reason, f"{context}.unsupported_scopes.{scope_name}")
        for scope_name, reason in unsupported_value.items()
    }
    if "user_skill" in data:
        user_skill_value = data.get("user_skill")
        user_skill = None if user_skill_value is None else _string(user_skill_value, f"{context}.user_skill")
    else:
        user_skill = f".{platform_key}/skills/graphify/SKILL.md"
    if "project_skill" in data:
        project_skill_value = data.get("project_skill")
        project_skill = None if project_skill_value is None else _string(project_skill_value, f"{context}.project_skill")
    else:
        project_skill = user_skill
    reference_bundles = tuple(
        _reference_bundle(bundle, f"{context}.reference_bundles[{index}]")
        for index, bundle in enumerate(_sequence(data.get("reference_bundles", []), f"{context}.reference_bundles"))
    )
    return InstallTargetSpec(
        name=name,
        display_name=None if data.get("display_name") is None else _string(data.get("display_name"), f"{context}.display_name"),
        target_kind=_string(data.get("target_kind", "product"), f"{context}.target_kind"),
        user_skill=user_skill,
        project_skill=project_skill,
        scopes=scopes,
        unsupported_scopes=unsupported_scopes,
        uses_packaged_references=_bool(data.get("uses_packaged_references", False if reference_bundles else True), f"{context}.uses_packaged_references"),
        reference_bundles=reference_bundles,
        simulated_linux_layout=simulated_linux_layout,
        universal_uninstall_scopes=_string_list(data.get("universal_uninstall_scopes", []), f"{context}.universal_uninstall_scopes"),
        target_runtime_validation=_platform_runtime_validations(data, context),
    )
