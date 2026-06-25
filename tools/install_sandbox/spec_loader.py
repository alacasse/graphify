from __future__ import annotations

try:
    from .registry.spec_loader import (
        DEFAULT_REGISTRY_PATH,
        SCHEMA_VERSION,
        InstallTargetCatalog,
        ScenarioRegistry,
        SpecLoaderError,
        load_default_registry,
        load_registry_from_data,
        load_registry_from_dir,
        load_registry_from_yaml,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from registry.spec_loader import (  # type: ignore[no-redef]
        DEFAULT_REGISTRY_PATH,
        SCHEMA_VERSION,
        InstallTargetCatalog,
        ScenarioRegistry,
        SpecLoaderError,
        load_default_registry,
        load_registry_from_data,
        load_registry_from_dir,
        load_registry_from_yaml,
    )

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "SCHEMA_VERSION",
    "InstallTargetCatalog",
    "ScenarioRegistry",
    "SpecLoaderError",
    "load_default_registry",
    "load_registry_from_data",
    "load_registry_from_dir",
    "load_registry_from_yaml",
]
