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

try:
    from ..harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
    from ..targets.install_target_catalog import InstallTargetCatalog, ScenarioRegistry
    from .spec_target_facts import SpecTargetFactError, platform_spec
    from .spec_install_surfaces import (
        SpecInstallSurfaceError,
        validate_install_surface_root,
        validate_relative_path,
    )
    from ..targets.install_target_models import (
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        InstallTargetSpec,
        UniversalUninstallScenarioSpec,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY  # type: ignore[no-redef]
    from registry.spec_target_facts import SpecTargetFactError, platform_spec  # type: ignore[no-redef]
    from registry.spec_install_surfaces import (  # type: ignore[no-redef]
        SpecInstallSurfaceError,
        validate_install_surface_root,
        validate_relative_path,
    )
    from targets.install_target_catalog import InstallTargetCatalog, ScenarioRegistry  # type: ignore[no-redef]
    from targets.install_target_models import (  # type: ignore[no-redef]
        DisposableArtifactScenarioSpec,
        DisposableSeedFile,
        InstallTargetSpec,
        UniversalUninstallScenarioSpec,
    )


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
        raise SpecLoaderError(str(exc)) from exc


def _validate_expected_root(root: str, context: str) -> None:
    try:
        validate_install_surface_root(root, context)
    except SpecInstallSurfaceError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _validate_cwd_root(root: str, context: str) -> None:
    all_roots = {sandbox_root.name for sandbox_root in DEFAULT_SANDBOX_ROOT_REGISTRY.roots}
    if root not in all_roots:
        _fail(context, f"unknown cwd root: {root}")


def _platform_spec(platform_key: str, value: object, context: str) -> InstallTargetSpec:
    try:
        return platform_spec(platform_key, value, context)
    except SpecTargetFactError as exc:
        raise SpecLoaderError(str(exc)) from exc


def _universal_uninstall(value: object, context: str) -> UniversalUninstallScenarioSpec:
    if isinstance(value, str):
        if value == "user":
            return UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-user",
                platform_label="multiple",
                scope="user",
                command=("graphify", "uninstall"),
                cwd_root="user_cwd",
                eligible_platform_scope="user",
            )
        if value == "project":
            return UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-project",
                platform_label="multiple",
                scope="project",
                command=("graphify", "uninstall", "--project"),
                cwd_root="project",
                eligible_platform_scope="project",
            )
        _fail(context, f"unknown compact universal uninstall scope: {value}")
    data = _mapping(value, context)
    cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
    _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    return UniversalUninstallScenarioSpec(
        scenario_id=_string(data.get("scenario_id"), f"{context}.scenario_id"),
        platform_label=_string(data.get("platform_label"), f"{context}.platform_label"),
        scope=_string(data.get("scope"), f"{context}.scope"),
        command=_command(data.get("command"), f"{context}.command"),
        cwd_root=cwd_root,
        eligible_platform_scope=_string(data.get("eligible_platform_scope"), f"{context}.eligible_platform_scope"),
        minimum_installed_scenarios=_int(data.get("minimum_installed_scenarios", 2), f"{context}.minimum_installed_scenarios"),
        artifact_subdir=_string(data.get("artifact_subdir", "uninstall"), f"{context}.artifact_subdir"),
        risk_note=_string(data.get("risk_note", "universal uninstall covers Graphify-owned file effects after multiple installs"), f"{context}.risk_note"),
    )


def _disposable_seed(value: object, context: str) -> DisposableSeedFile:
    data = _mapping(value, context)
    relative = _string(data.get("relative"), f"{context}.relative")
    _validate_relative(relative, f"{context}.relative")
    return DisposableSeedFile(relative, _string(data.get("content"), f"{context}.content"))


def _disposable_artifact(value: object, context: str) -> DisposableArtifactScenarioSpec:
    data = _mapping(value, context)
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


def load_registry_from_data(data: object, *, source: str = "<data>") -> InstallTargetCatalog:
    registry = _mapping(data, source)
    version = registry.get("schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"expected schema version {SCHEMA_VERSION}")
    platforms_value = _mapping(registry.get("platforms"), f"{source}.platforms")
    platform_names = tuple(platforms_value.keys())

    specs = {
        platform_name: _platform_spec(
            platform_name,
            platforms_value[platform_name],
            f"{source}.platforms.{platform_name}",
        )
        for platform_name in platform_names
    }
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
    loaded = ScenarioRegistry(specs, universal_uninstall_specs=universal, disposable_artifact_specs=disposable)
    loaded.validate_roots({root.name for root in DEFAULT_SANDBOX_ROOT_REGISTRY.roots})
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
