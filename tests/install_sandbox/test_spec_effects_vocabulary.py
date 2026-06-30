from __future__ import annotations

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox.registry.spec_loader import load_registry_from_data
from tools.install_sandbox.registry.spec_normalize import normalize_registry


def test_loader_prefers_effects_key_for_install_surface_inputs() -> None:
    effects_data = _valid_data()

    registry = load_registry_from_data(effects_data)
    user = registry.make_scenario("mini", "user")
    project = registry.make_scenario("mini", "project")

    assert user is not None
    assert project is not None
    assert not hasattr(user, "effects")
    assert not hasattr(project, "effects")
    normalized_user = normalize_registry(registry)["platforms"]["mini"]["scopes"]["user"]
    assert normalized_user["effects"] == normalized_user["expected"]


def test_loader_rejects_scope_with_expected_and_effects() -> None:
    data = _valid_data()
    user_scope = data["platforms"]["mini"]["scopes"]["user"]
    user_scope["expected"] = list(user_scope["effects"])

    _expect_invalid(data, "declare only one of expected or effects")


def test_loader_rejects_scope_without_expected_or_effects() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"].pop("effects")

    _expect_invalid(data, "runnable scope must declare expected or effects")
