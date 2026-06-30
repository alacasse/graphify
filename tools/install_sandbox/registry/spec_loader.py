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

from ..harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
from .. import validation_plan
from ..targets.install_target_catalog import InstallTargetCatalog, ScenarioRegistry
from ..targets.install_target_models import PlatformSpec
from .spec_harness_policy_inputs import (
    SpecHarnessPolicyInputError,
    parse_top_level_policy_inputs,
)
from .spec_target_facts import SpecTargetFactError, target_spec


SCHEMA_VERSION = 1
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "specs"


class SpecLoaderError(ValueError):
    pass


def _fail(context: str, message: str) -> None:
    raise SpecLoaderError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


def _target_spec(platform_key: str, value: object, context: str) -> PlatformSpec:
    try:
        return target_spec(platform_key, value, context)
    except SpecTargetFactError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _top_level_policy_inputs(registry: Mapping[str, Any], source: str):
    try:
        return parse_top_level_policy_inputs(registry, source=source)
    except SpecHarnessPolicyInputError as exc:
        raise SpecLoaderError(str(exc)) from exc


def load_registry_from_data(data: object, *, source: str = "<data>") -> InstallTargetCatalog:
    registry = _mapping(data, source)
    version = registry.get("schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"expected schema version {SCHEMA_VERSION}")
    platforms_value = _mapping(registry.get("platforms"), f"{source}.platforms")
    platform_names = tuple(platforms_value.keys())

    specs = {
        platform_name: _target_spec(
            platform_name,
            platforms_value[platform_name],
            f"{source}.platforms.{platform_name}",
        )
        for platform_name in platform_names
    }
    universal, disposable = _top_level_policy_inputs(registry, source)
    loaded = ScenarioRegistry(specs, universal_uninstall_specs=universal, disposable_artifact_specs=disposable)
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
        _fail(str(registry_dir), "expected at least one platform spec file")

    data = {
        "schema_version": SCHEMA_VERSION,
        "platforms": {
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
