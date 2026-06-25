from __future__ import annotations

import pytest

from tools.install_sandbox import platform_specs
from tools.install_sandbox.targets import install_target_defaults

from install_target_test_support import REGISTRY


def test_default_catalog_helpers_live_in_install_target_defaults() -> None:
    helper_names = (
        "default_install_target_catalog",
        "install_target_specs",
        "install_target_spec",
        "install_target_scenarios",
        "platform_spec",
        "platform_scenarios",
        "make_scenario",
        "risk_notes",
        "validate_roots",
    )

    for name in helper_names:
        assert getattr(platform_specs, name) is getattr(install_target_defaults, name)


def test_install_target_module_helpers_use_default_catalog_seam() -> None:
    catalog = install_target_defaults.default_install_target_catalog()

    assert catalog is REGISTRY
    assert install_target_defaults.install_target_specs() is catalog.specs
    assert install_target_defaults.install_target_spec("codex") is catalog.target_spec("codex")
    assert install_target_defaults.install_target_scenarios("cursor", "both") == catalog.target_scenarios("cursor", "both")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        install_target_defaults.install_target_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        install_target_defaults.install_target_scenarios("missing-target", "both")


def test_install_target_helpers_use_replaced_default_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "cached-target": platform_specs.PlatformSpec(
                name="cached-target",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "cached.txt"),),
                    )
                },
            )
        }
    )
    monkeypatch.setattr(install_target_defaults, "_DEFAULT_SCENARIO_REGISTRY", registry)

    assert install_target_defaults.default_install_target_catalog() is registry
    assert install_target_defaults.install_target_specs() is registry.specs
    assert install_target_defaults.install_target_spec("cached-target") is registry.target_spec("cached-target")
    assert install_target_defaults.install_target_scenarios("cached-target", "project") == registry.target_scenarios(
        "cached-target",
        "project",
    )


def test_lazy_default_catalog_exports_share_one_cache_for_compatibility_names(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    registry = platform_specs.ScenarioRegistry(
        {
            "cached-target": platform_specs.PlatformSpec(
                name="cached-target",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.InstallSurface("project", "cached.txt"),),
                    )
                },
            )
        }
    )

    def load_default_registry():
        nonlocal calls
        calls += 1
        return registry

    monkeypatch.setattr(install_target_defaults, "_DEFAULT_SCENARIO_REGISTRY", None)
    monkeypatch.setitem(install_target_defaults.__dict__, "_import_load_default_registry", lambda: load_default_registry)
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        monkeypatch.delitem(platform_specs.__dict__, name, raising=False)
        monkeypatch.delitem(install_target_defaults.__dict__, name, raising=False)

    assert install_target_defaults.default_install_target_catalog() is registry
    assert platform_specs.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry
    assert platform_specs.__getattr__("SANDBOX_PLATFORM_SPECS") is registry.specs
    assert platform_specs.__getattr__("ALL_PLATFORMS") == ["cached-target"]
    assert install_target_defaults.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry
    assert calls == 1
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        platform_specs.__dict__.pop(name, None)
        install_target_defaults.__dict__.pop(name, None)
