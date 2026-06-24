from __future__ import annotations

from copy import deepcopy

import pytest
import yaml

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox import spec_loader
from tools.install_sandbox.spec_loader import load_registry_from_data
from tools.install_sandbox.spec_normalize import normalize_registry


DEFAULT_EFFECTS_SPECS = {
    "agents",
    "aider",
    "amp",
    "antigravity",
    "antigravity-windows",
    "claw",
    "claude",
    "codebuddy",
    "codex",
    "copilot",
    "cursor",
    "devin",
    "droid",
    "gemini",
    "hermes",
    "kimi",
    "kiro",
    "kilo",
    "opencode",
    "pi",
    "trae",
    "trae-cn",
    "vscode",
    "windows",
}


def _default_scope_effect_key_inventory() -> dict[str, set[str]]:
    inventory = {"expected": set(), "effects": set(), "missing": set(), "mixed": set()}
    for path in sorted(spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")):
        if path.name == "shared.yaml":
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for scope_name, scope_data in data.get("scopes", {}).items():
            scope_id = f"{path.stem}.{scope_name}"
            has_expected = "expected" in scope_data
            has_effects = "effects" in scope_data
            if has_expected and has_effects:
                inventory["mixed"].add(scope_id)
            elif has_effects:
                inventory["effects"].add(scope_id)
            elif has_expected:
                inventory["expected"].add(scope_id)
            else:
                inventory["missing"].add(scope_id)
    return inventory


def test_loader_accepts_effects_key_equivalent_to_expected() -> None:
    expected_data = _valid_data()
    effects_data = deepcopy(expected_data)
    for scope in effects_data["platforms"]["mini"]["scopes"].values():
        scope["effects"] = scope.pop("expected")

    assert normalize_registry(load_registry_from_data(effects_data)) == normalize_registry(load_registry_from_data(expected_data))


def test_loader_rejects_scope_with_expected_and_effects() -> None:
    data = _valid_data()
    user_scope = data["platforms"]["mini"]["scopes"]["user"]
    user_scope["effects"] = deepcopy(user_scope["expected"])

    _expect_invalid(data, "declare only one of expected or effects")


def test_loader_rejects_scope_without_expected_or_effects() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"].pop("expected")

    _expect_invalid(data, "runnable scope must declare expected or effects")


def test_default_registry_runnable_scopes_declare_one_effect_vocabulary_key() -> None:
    inventory = _default_scope_effect_key_inventory()

    assert inventory["mixed"] == set()
    assert inventory["missing"] == set()
    assert inventory["effects"]
    assert inventory["expected"] == set()


def test_default_registry_all_runnable_scopes_use_effects() -> None:
    inventory = _default_scope_effect_key_inventory()
    effects_specs = {scope_id.split(".", maxsplit=1)[0] for scope_id in inventory["effects"]}
    all_specs = {
        path.stem
        for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")
        if path.name != "shared.yaml"
    }

    assert effects_specs == all_specs == DEFAULT_EFFECTS_SPECS
    assert inventory["expected"] == set()


@pytest.mark.parametrize("spec_name", sorted(DEFAULT_EFFECTS_SPECS))
def test_default_registry_migrated_yaml_uses_effects_key_for_runnable_scopes(spec_name: str) -> None:
    data = yaml.safe_load((spec_loader.DEFAULT_REGISTRY_PATH / f"{spec_name}.yaml").read_text(encoding="utf-8"))

    assert data["scopes"]
    for scope in data["scopes"].values():
        assert "effects" in scope
        assert "expected" not in scope
