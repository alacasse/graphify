from __future__ import annotations

import inspect

import pytest

from tools.install_sandbox.surfaces.install_surface_models import ExpectedPath
from tools.install_sandbox.targets import install_target_catalog, install_target_models
from tools.install_sandbox.targets import install_target_defaults


DEFAULT_TARGET_HELPER_TARGET_OWNER_PARAMETERS = {
    "direct_install_command": {"target_name"},
    "direct_uninstall_command": {"target_name"},
    "generic_install_command": {"target_name"},
    "install_target_scenarios": {"target_name"},
    "install_target_spec": {"target_name"},
    "make_scenario": {"target_name"},
    "project_skill": {"target_name"},
    "risk_notes": {"target_name"},
    "unsupported_scope_reason": {"target_name"},
    "universal_uninstall_scenarios": {"target_names"},
    "user_skill": {"target_name"},
}

DEFAULT_TARGET_HELPER_PLATFORM_NAMED_PARAMETER_DEBT: dict[str, set[str]] = {}

DEFERRED_DEFAULT_EDGE_VOCABULARY = {
    "normalized YAML platforms output",
    "--platform command argument",
}


def test_default_catalog_target_helpers_live_in_install_target_defaults() -> None:
    helper_names = (
        "default_install_target_catalog",
        "install_target_specs",
        "install_target_spec",
        "install_target_scenarios",
        "make_scenario",
        "risk_notes",
        "validate_roots",
    )

    for name in helper_names:
        assert callable(getattr(install_target_defaults, name))


def test_default_catalog_platform_helpers_are_removed() -> None:
    for name in ("platform_spec", "platform_scenarios", "sandbox_platform_specs"):
        assert not hasattr(install_target_defaults, name)


def test_default_target_helpers_use_target_owned_parameters_for_install_targets() -> None:
    assert DEFERRED_DEFAULT_EDGE_VOCABULARY == {
        "normalized YAML platforms output",
        "--platform command argument",
    }
    legacy_parameter_names = {"platform_name", "platforms"}
    for helper_name, target_parameters in DEFAULT_TARGET_HELPER_TARGET_OWNER_PARAMETERS.items():
        signature = inspect.signature(getattr(install_target_defaults, helper_name))

        assert set(signature.parameters) >= target_parameters
        assert not (set(signature.parameters) & legacy_parameter_names)


def test_default_target_helpers_classify_remaining_platform_parameters_as_internal_debt() -> None:
    assert DEFAULT_TARGET_HELPER_PLATFORM_NAMED_PARAMETER_DEBT == {}
    for helper_name, debt_parameters in DEFAULT_TARGET_HELPER_PLATFORM_NAMED_PARAMETER_DEBT.items():
        signature = inspect.signature(getattr(install_target_defaults, helper_name))

        assert set(signature.parameters) >= debt_parameters


def test_install_target_module_helpers_use_default_catalog_seam() -> None:
    catalog = install_target_defaults.default_install_target_catalog()

    assert install_target_defaults.install_target_specs() is catalog.specs
    assert install_target_defaults.install_target_spec("codex") is catalog.target_spec("codex")
    assert install_target_defaults.install_target_scenarios("cursor", "both") == catalog.target_scenarios("cursor", "both")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        install_target_defaults.install_target_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        install_target_defaults.install_target_scenarios("missing-target", "both")


def test_install_target_helpers_use_replaced_default_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = install_target_catalog.InstallTargetCatalog(
        {
            "cached-target": install_target_models.InstallTargetSpec(
                name="cached-target",
                scopes={
                    "project": install_target_models.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(ExpectedPath("project", "cached.txt"),),
                    )
                },
            )
        }
    )
    monkeypatch.setattr(install_target_defaults, "_DEFAULT_INSTALL_TARGET_CATALOG", catalog)

    assert install_target_defaults.default_install_target_catalog() is catalog
    assert install_target_defaults.install_target_specs() is catalog.specs
    assert install_target_defaults.install_target_spec("cached-target") is catalog.target_spec("cached-target")
    assert install_target_defaults.install_target_scenarios("cached-target", "project") == catalog.target_scenarios(
        "cached-target",
        "project",
    )


def test_lazy_default_catalog_exports_share_one_cache_for_supported_names(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    catalog = install_target_catalog.InstallTargetCatalog(
        {
            "cached-target": install_target_models.InstallTargetSpec(
                name="cached-target",
                scopes={
                    "project": install_target_models.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(install_target_models.InstallSurface("project", "cached.txt"),),
                    )
                },
            )
        }
    )

    def load_default_registry():
        nonlocal calls
        calls += 1
        return catalog

    monkeypatch.setattr(install_target_defaults, "_DEFAULT_INSTALL_TARGET_CATALOG", None)
    monkeypatch.setitem(install_target_defaults.__dict__, "_import_load_default_registry", lambda: load_default_registry)
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        monkeypatch.delitem(install_target_defaults.__dict__, name, raising=False)

    assert install_target_defaults.default_install_target_catalog() is catalog
    assert install_target_defaults.__getattr__("DEFAULT_INSTALL_TARGET_CATALOG") is catalog
    with pytest.raises(AttributeError):
        install_target_defaults.__getattr__("DEFAULT_SCENARIO_REGISTRY")
    with pytest.raises(AttributeError):
        install_target_defaults.__getattr__("SANDBOX_PLATFORM_SPECS")
    with pytest.raises(AttributeError):
        install_target_defaults.__getattr__("ALL_PLATFORMS")
    assert calls == 1
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        install_target_defaults.__dict__.pop(name, None)
