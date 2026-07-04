from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency is declared for dev/test use
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None

from ..sandbox_roots import DEFAULT_SANDBOX_ROOT_REGISTRY
from .. import validation_plan
from ..targets.install_target_catalog import InstallTargetCatalog
from ..targets.install_target_models import InstallTargetSpec
from .spec_harness_policy_inputs import (
    SpecHarnessPolicyInputError,
    TOP_LEVEL_TRANSITIONAL_POLICY_INPUT_FIELDS,
    parse_top_level_policy_inputs,
)
from .spec_schema_validation import (
    CURRENT_REGISTRY_CONTAINER_FIELD,
    LEGACY_REGISTRY_CONTAINER_FIELD,
    SpecSchemaValidationError,
    reject_unknown_fields,
)
from .spec_target_facts import SpecTargetFactError, target_spec


SCHEMA_VERSION = 1
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "specs"
_TOP_LEVEL_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        CURRENT_REGISTRY_CONTAINER_FIELD,
        LEGACY_REGISTRY_CONTAINER_FIELD,
        *TOP_LEVEL_TRANSITIONAL_POLICY_INPUT_FIELDS,
    }
)


class SpecLoaderError(ValueError):
    pass

def _fail(context: str, message: str) -> None:
    raise SpecLoaderError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


def _reject_unknown_fields(data: Mapping[str, object], allowed: frozenset[str], context: str) -> None:
    try:
        reject_unknown_fields(data, allowed, context)
    except SpecSchemaValidationError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _target_spec(target_name: str, value: object, context: str) -> InstallTargetSpec:
    try:
        return target_spec(target_name, value, context)
    except SpecTargetFactError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _top_level_policy_inputs(registry: Mapping[str, Any], source: str):
    try:
        return parse_top_level_policy_inputs(registry, source=source)
    except SpecHarnessPolicyInputError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _registry_targets(registry: Mapping[str, Any], source: str) -> tuple[Mapping[str, Any], str]:
    has_current = CURRENT_REGISTRY_CONTAINER_FIELD in registry
    has_legacy = LEGACY_REGISTRY_CONTAINER_FIELD in registry
    if has_current and has_legacy:
        _fail(
            source,
            f"declares both {CURRENT_REGISTRY_CONTAINER_FIELD} and legacy {LEGACY_REGISTRY_CONTAINER_FIELD}",
        )
    if has_current:
        context = f"{source}.{CURRENT_REGISTRY_CONTAINER_FIELD}"
        return _mapping(registry[CURRENT_REGISTRY_CONTAINER_FIELD], context), context
    if has_legacy:
        context = f"{source}.{LEGACY_REGISTRY_CONTAINER_FIELD}"
        return _mapping(registry[LEGACY_REGISTRY_CONTAINER_FIELD], context), context
    _fail(source, f"expected {CURRENT_REGISTRY_CONTAINER_FIELD} registry container")


def load_registry_from_data(data: object, *, source: str = "<data>") -> InstallTargetCatalog:
    registry = _mapping(data, source)
    _reject_unknown_fields(registry, _TOP_LEVEL_REGISTRY_FIELDS, source)
    version = registry.get("schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"expected schema version {SCHEMA_VERSION}")
    targets_value, targets_context = _registry_targets(registry, source)
    target_names = tuple(targets_value.keys())

    specs = {
        target_name: _target_spec(
            target_name,
            targets_value[target_name],
            f"{targets_context}.{target_name}",
        )
        for target_name in target_names
    }
    universal, disposable = _top_level_policy_inputs(registry, source)
    loaded = InstallTargetCatalog(specs, universal_uninstall_specs=universal, disposable_artifact_specs=disposable)
    declared_roots = DEFAULT_SANDBOX_ROOT_REGISTRY.root_names()
    loaded.validate_target_roots(declared_roots)
    validation_plan.validate_policy_owned_roots(
        loaded,
        validation_plan.DEFAULT_HARNESS_POLICY,
        declared_roots,
    )
    return loaded


def _load_yaml_data(path: Path) -> object:
    if yaml is None:
        raise SpecLoaderError("PyYAML is required to load install sandbox YAML specs") from _YAML_IMPORT_ERROR
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_registry_from_dir(path: Path | str = DEFAULT_REGISTRY_PATH) -> InstallTargetCatalog:
    registry_dir = Path(path)
    product_paths = sorted(
        (
            product_path
            for product_path in registry_dir.glob("*.yaml")
            if product_path.name != "shared.yaml"
        ),
        key=lambda product_path: product_path.stem,
    )
    if not product_paths:
        _fail(str(registry_dir), "expected at least one target spec file")

    data = {
        "schema_version": SCHEMA_VERSION,
        CURRENT_REGISTRY_CONTAINER_FIELD: {
            product_path.stem: _load_yaml_data(product_path)
            for product_path in product_paths
        },
    }
    return load_registry_from_data(data, source=str(registry_dir))


def load_registry_from_yaml(path: Path | str = DEFAULT_REGISTRY_PATH) -> InstallTargetCatalog:
    registry_path = Path(path)
    if registry_path.is_dir():
        return load_registry_from_dir(registry_path)
    data = _load_yaml_data(registry_path)
    return load_registry_from_data(data, source=str(registry_path))


def load_default_registry() -> InstallTargetCatalog:
    return load_registry_from_dir(DEFAULT_REGISTRY_PATH)
