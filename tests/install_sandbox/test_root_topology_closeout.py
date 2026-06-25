from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"


def test_root_topology_closeout_keeps_moved_implementation_packages_importable() -> None:
    for module_name in (
        "tools.install_sandbox.registry.spec_loader",
        "tools.install_sandbox.registry.spec_normalize",
        "tools.install_sandbox.reporting.reports",
        "tools.install_sandbox.reporting.agent_summary",
        "tools.install_sandbox.runtime.command_runner",
        "tools.install_sandbox.runtime.container_runtime",
        "tools.install_sandbox.runtime.source_snapshot",
    ):
        assert importlib.import_module(module_name).__name__ == module_name


def test_root_topology_closeout_keeps_old_implementation_modules_absent() -> None:
    for module_name in ("reports", "command_runner", "container_runtime", "source_snapshot"):
        assert not (INSTALL_SANDBOX_ROOT / f"{module_name}.py").exists()
        assert importlib.util.find_spec(f"tools.install_sandbox.{module_name}") is None


def test_root_topology_closeout_keeps_batch_compatibility_facades_importable() -> None:
    root_agent_summary = importlib.import_module("tools.install_sandbox.agent_summary")
    owner_agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    root_spec_loader = importlib.import_module("tools.install_sandbox.spec_loader")
    owner_spec_loader = importlib.import_module("tools.install_sandbox.registry.spec_loader")
    root_spec_normalize = importlib.import_module("tools.install_sandbox.spec_normalize")
    owner_spec_normalize = importlib.import_module("tools.install_sandbox.registry.spec_normalize")

    assert (INSTALL_SANDBOX_ROOT / "agent_summary.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "spec_loader.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "spec_normalize.py").exists()
    assert root_agent_summary.summarize_output is owner_agent_summary.summarize_output
    assert root_spec_loader.load_default_registry is owner_spec_loader.load_default_registry
    assert root_spec_normalize.normalize_registry is owner_spec_normalize.normalize_registry
