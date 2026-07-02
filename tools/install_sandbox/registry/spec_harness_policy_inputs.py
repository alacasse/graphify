from __future__ import annotations

from typing import Any, Mapping

from ..sandbox_roots import DEFAULT_SANDBOX_ROOT_REGISTRY
from ..targets.install_target_models import (
    DisposableArtifactScenarioSpec,
    DisposableSeedFile,
    UniversalUninstallScenarioSpec,
)
from .spec_install_surfaces import (
    SpecInstallSurfaceError,
    validate_install_surface_root,
    validate_relative_path,
)
from .spec_schema_validation import SpecSchemaValidationError, reject_unknown_fields


TOP_LEVEL_TRANSITIONAL_POLICY_INPUT_FIELDS = frozenset(
    {
        "universal_uninstall_specs",
        "disposable_artifact_specs",
    }
)
_UNIVERSAL_UNINSTALL_FIELDS = frozenset(
    {
        "artifact_subdir",
        "command",
        "cwd_root",
        "eligible_platform_scope",
        "minimum_installed_scenarios",
        "platform_label",
        "risk_note",
        "scenario_id",
        "scope",
    }
)
_DISPOSABLE_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_subdir",
        "command",
        "cwd_root",
        "disposable_path_relative",
        "disposable_path_root",
        "platform_label",
        "risk_note",
        "scenario_id",
        "scope",
        "scope_eligibility",
        "seed_files",
    }
)
_DISPOSABLE_SEED_FIELDS = frozenset({"content", "relative"})


class SpecHarnessPolicyInputError(ValueError):
    pass


def _fail(context: str, message: str) -> None:
    raise SpecHarnessPolicyInputError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


def _reject_unknown_fields(data: Mapping[str, object], allowed: frozenset[str], context: str) -> None:
    try:
        reject_unknown_fields(data, allowed, context)
    except SpecSchemaValidationError as exc:
        raise SpecHarnessPolicyInputError(str(exc)) from exc


def _sequence(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(context, "expected list")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(context, "expected non-empty string")
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


def _validate_relative(relative: str, context: str) -> None:
    try:
        validate_relative_path(relative, context)
    except SpecInstallSurfaceError as exc:
        raise SpecHarnessPolicyInputError(str(exc)) from exc


def _validate_expected_root(root: str, context: str) -> None:
    try:
        validate_install_surface_root(root, context)
    except SpecInstallSurfaceError as exc:
        raise SpecHarnessPolicyInputError(str(exc)) from exc


def _validate_cwd_root(root: str, context: str) -> None:
    if root not in DEFAULT_SANDBOX_ROOT_REGISTRY.policy_cwd_root_names():
        _fail(context, f"unknown cwd root: {root}")


def _universal_uninstall(value: object, context: str) -> UniversalUninstallScenarioSpec:
    if isinstance(value, str):
        if value == "user":
            return UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-user",
                platform_label="multiple",
                scope="user",
                command=("graphify", "uninstall"),
                cwd_root="user_cwd",
                eligible_target_scope="user",
            )
        if value == "project":
            return UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-project",
                platform_label="multiple",
                scope="project",
                command=("graphify", "uninstall", "--project"),
                cwd_root="project",
                eligible_target_scope="project",
            )
        _fail(context, f"unknown compact universal uninstall scope: {value}")
    data = _mapping(value, context)
    _reject_unknown_fields(data, _UNIVERSAL_UNINSTALL_FIELDS, context)
    cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
    _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    return UniversalUninstallScenarioSpec(
        scenario_id=_string(data.get("scenario_id"), f"{context}.scenario_id"),
        platform_label=_string(data.get("platform_label"), f"{context}.platform_label"),
        scope=_string(data.get("scope"), f"{context}.scope"),
        command=_command(data.get("command"), f"{context}.command"),
        cwd_root=cwd_root,
        eligible_target_scope=_string(data.get("eligible_platform_scope"), f"{context}.eligible_platform_scope"),
        minimum_installed_scenarios=_int(data.get("minimum_installed_scenarios", 2), f"{context}.minimum_installed_scenarios"),
        artifact_subdir=_string(data.get("artifact_subdir", "uninstall"), f"{context}.artifact_subdir"),
        risk_note=_string(data.get("risk_note", "universal uninstall covers Graphify-owned file effects after multiple installs"), f"{context}.risk_note"),
    )


def _disposable_seed(value: object, context: str) -> DisposableSeedFile:
    data = _mapping(value, context)
    _reject_unknown_fields(data, _DISPOSABLE_SEED_FIELDS, context)
    relative = _string(data.get("relative"), f"{context}.relative")
    _validate_relative(relative, f"{context}.relative")
    return DisposableSeedFile(relative, _string(data.get("content"), f"{context}.content"))


def _disposable_artifact(value: object, context: str) -> DisposableArtifactScenarioSpec:
    data = _mapping(value, context)
    _reject_unknown_fields(data, _DISPOSABLE_ARTIFACT_FIELDS, context)
    cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
    _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    disposable_path_root = _string(data.get("disposable_path_root"), f"{context}.disposable_path_root")
    _validate_expected_root(disposable_path_root, f"{context}.disposable_path_root")
    disposable_path_relative = _string(data.get("disposable_path_relative"), f"{context}.disposable_path_relative")
    _validate_relative(disposable_path_relative, f"{context}.disposable_path_relative")
    return DisposableArtifactScenarioSpec(
        scenario_id=_string(data.get("scenario_id"), f"{context}.scenario_id"),
        platform_label=_string(data.get("platform_label"), f"{context}.platform_label"),
        scope=_string(data.get("scope"), f"{context}.scope"),
        command=_command(data.get("command"), f"{context}.command"),
        cwd_root=cwd_root,
        artifact_subdir=_string(data.get("artifact_subdir"), f"{context}.artifact_subdir"),
        disposable_path_root=disposable_path_root,
        disposable_path_relative=disposable_path_relative,
        seed_files=tuple(
            _disposable_seed(seed, f"{context}.seed_files[{index}]")
            for index, seed in enumerate(_sequence(data.get("seed_files", []), f"{context}.seed_files"))
        ),
        scope_eligibility=_string_list(data.get("scope_eligibility"), f"{context}.scope_eligibility", allow_empty=False),
        risk_note=_string(data.get("risk_note"), f"{context}.risk_note"),
    )


def parse_top_level_policy_inputs(
    registry: Mapping[str, Any],
    *,
    source: str,
) -> tuple[tuple[UniversalUninstallScenarioSpec, ...], tuple[DisposableArtifactScenarioSpec, ...]]:
    if "universal_uninstall_specs" in registry:
        universal = tuple(
            _universal_uninstall(spec, f"{source}.universal_uninstall_specs[{index}]")
            for index, spec in enumerate(_sequence(registry.get("universal_uninstall_specs"), f"{source}.universal_uninstall_specs"))
        )
    else:
        universal = ()
    if "disposable_artifact_specs" in registry:
        disposable = tuple(
            _disposable_artifact(spec, f"{source}.disposable_artifact_specs[{index}]")
            for index, spec in enumerate(_sequence(registry.get("disposable_artifact_specs"), f"{source}.disposable_artifact_specs"))
        )
    else:
        disposable = ()
    return universal, disposable
