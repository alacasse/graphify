from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import yaml

from tools.install_sandbox.registry import spec_loader
from tools.install_sandbox.registry.spec_loader import (
    SpecLoaderError,
    load_default_registry,
    load_registry_from_data,
    load_registry_from_dir,
)

from tests.install_sandbox.install_target_test_support import (
    valid_registry_data as _valid_data,
    write_registry_dir as _write_registry_dir,
)


def test_default_registry_discovers_product_yaml_files_in_filename_order() -> None:
    registry = load_default_registry()
    expected = sorted(
        product_path.stem
        for product_path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")
        if product_path.name != "shared.yaml"
    )

    assert registry.target_names == expected


def test_load_registry_from_dir_does_not_supply_synthetic_registry_policies(tmp_path: Any) -> None:
    data = _valid_data()
    data["platforms"]["mini"]["simulated_linux_layout"] = True
    _write_registry_dir(tmp_path, data)

    registry = load_registry_from_dir(tmp_path)

    assert registry.universal_uninstall_specs == ()
    assert registry.disposable_artifact_specs == ()
    assert registry.target_spec("mini").target_runtime_validation == ()


def test_load_registry_from_dir_rejects_empty_product_specs(tmp_path: Any) -> None:
    data = _valid_data()
    _write_registry_dir(tmp_path, data)
    (tmp_path / "mini.yaml").unlink()

    with pytest.raises(SpecLoaderError, match="expected at least one platform spec file"):
        load_registry_from_dir(tmp_path)


def test_load_registry_from_dir_discovers_added_product_yaml_files(tmp_path: Any) -> None:
    data = _valid_data()
    _write_registry_dir(tmp_path, data)
    (tmp_path / "alpha.yaml").write_text(yaml.safe_dump(deepcopy(data["platforms"]["mini"]), sort_keys=False), encoding="utf-8")

    registry = load_registry_from_dir(tmp_path)

    assert registry.target_names == ["alpha", "mini"]


def test_load_registry_from_dir_rejects_filename_key_mismatch(tmp_path: Any) -> None:
    data = _valid_data()
    data["platforms"]["mini"]["name"] = "other"
    _write_registry_dir(tmp_path, data)

    with pytest.raises(SpecLoaderError, match="platform key/name mismatch: mini != other"):
        load_registry_from_dir(tmp_path)


def test_load_registry_from_dir_uses_deterministic_filename_order(tmp_path: Any) -> None:
    data = _valid_data()
    mini = deepcopy(data["platforms"]["mini"])
    data["platforms"] = {
        "beta": deepcopy(mini),
        "alpha": deepcopy(mini),
    }
    _write_registry_dir(tmp_path, data)

    registry = load_registry_from_dir(tmp_path)

    assert registry.target_names == ["alpha", "beta"]


def test_load_registry_from_dir_ignores_shared_yaml_and_orders_by_filename_stem(
    tmp_path: Any,
) -> None:
    data = _valid_data()
    mini = deepcopy(data["platforms"]["mini"])
    (tmp_path / "beta.yaml").write_text(yaml.safe_dump(mini, sort_keys=False), encoding="utf-8")
    (tmp_path / "alpha.yaml").write_text(yaml.safe_dump(mini, sort_keys=False), encoding="utf-8")
    (tmp_path / "shared.yaml").write_text(
        yaml.safe_dump({"not": "a platform spec"}, sort_keys=False),
        encoding="utf-8",
    )

    registry = load_registry_from_dir(tmp_path)

    assert registry.target_names == ["alpha", "beta"]


def test_load_registry_from_data_uses_platform_mapping_order() -> None:
    data = deepcopy(_valid_data())
    mini = deepcopy(data["platforms"]["mini"])
    data["platforms"] = {
        "zeta": deepcopy(mini),
        "alpha": deepcopy(mini),
    }

    registry = load_registry_from_data(data)

    assert registry.target_names == ["zeta", "alpha"]
