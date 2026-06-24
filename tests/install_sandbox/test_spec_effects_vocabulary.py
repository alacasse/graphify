from __future__ import annotations

from copy import deepcopy

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox.spec_loader import load_registry_from_data
from tools.install_sandbox.spec_normalize import normalize_registry


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
