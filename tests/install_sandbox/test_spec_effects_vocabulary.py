from __future__ import annotations

from copy import deepcopy

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_effects_registry_data as _valid_effects_data,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox.spec_loader import load_registry_from_data
from tools.install_sandbox.spec_normalize import normalize_registry


def test_loader_prefers_effects_key_for_install_surface_inputs() -> None:
    effects_data = _valid_effects_data()

    registry = load_registry_from_data(effects_data)
    user = registry.make_scenario("mini", "user")
    project = registry.make_scenario("mini", "project")

    assert user is not None
    assert project is not None
    assert user.effects == user.expected
    assert project.effects == project.expected
    normalized_user = normalize_registry(registry)["platforms"]["mini"]["scopes"]["user"]
    assert normalized_user["effects"] == normalized_user["expected"]


def test_loader_retains_expected_key_as_legacy_compatibility() -> None:
    expected_data = _valid_data()
    effects_data = _valid_effects_data()

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
