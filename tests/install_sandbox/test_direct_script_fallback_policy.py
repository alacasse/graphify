"""Direct-runner fallback policy for install-sandbox modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

SUPPORTED_DIRECT_ENTRYPOINTS = {
    "host_runner": Path("tools/install_sandbox/run.py"),
    "sandbox_runner_file": Path("tools/install_sandbox/sandbox_runner.py"),
    "sandbox_runner_module": "tools.install_sandbox.sandbox_runner",
    "reporting_agent_summary_file": Path("tools/install_sandbox/reporting/agent_summary.py"),
    "reporting_agent_summary_module": "tools.install_sandbox.reporting.agent_summary",
    "validation_plan_direct_import": Path("tools/install_sandbox/validation_plan.py"),
}

NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES = {
    Path("tools/install_sandbox/effects/file_effect_generated_artifacts.py"),
    Path("tools/install_sandbox/effects/file_effect_oracle.py"),
    Path("tools/install_sandbox/effects/file_effect_sidecars.py"),
    Path("tools/install_sandbox/effects/file_effect_state.py"),
    Path("tools/install_sandbox/effects/file_effect_surfaces.py"),
    Path("tools/install_sandbox/effects/scenario_file_effects_adapter.py"),
    Path("tools/install_sandbox/lifecycle/scenario_lifecycle_disposable.py"),
    Path("tools/install_sandbox/lifecycle/scenario_lifecycle_plan.py"),
    Path("tools/install_sandbox/lifecycle/scenario_lifecycle_standard.py"),
    Path("tools/install_sandbox/lifecycle/scenario_lifecycle_support.py"),
    Path("tools/install_sandbox/lifecycle/scenario_lifecycle_universal.py"),
    Path("tools/install_sandbox/surfaces/install_surface_generated.py"),
    Path("tools/install_sandbox/surfaces/install_surface_sidecars.py"),
    Path("tools/install_sandbox/surfaces/install_surface_state.py"),
    Path("tools/install_sandbox/surfaces/install_surface_statuses.py"),
    Path("tools/install_sandbox/surfaces/path_resolution.py"),
}

REMOVED_RUNTIME_REPORTING_FALLBACKS = {
    Path("tools/install_sandbox/reporting/reports.py"),
    Path("tools/install_sandbox/runtime/harness_orchestration.py"),
    Path("tools/install_sandbox/runtime/sandbox_run_environment.py"),
}

REMOVED_REGISTRY_TARGET_FALLBACKS = {
    Path("tools/install_sandbox/registry/spec_harness_policy_inputs.py"),
    Path("tools/install_sandbox/registry/spec_install_surfaces.py"),
    Path("tools/install_sandbox/registry/spec_loader.py"),
    Path("tools/install_sandbox/registry/spec_normalize.py"),
    Path("tools/install_sandbox/registry/spec_target_facts.py"),
    Path("tools/install_sandbox/targets/install_target_catalog.py"),
    Path("tools/install_sandbox/targets/install_target_defaults.py"),
    Path("tools/install_sandbox/targets/install_target_harness_policy.py"),
    Path("tools/install_sandbox/targets/install_target_models.py"),
    Path("tools/install_sandbox/targets/install_target_scenarios.py"),
    Path("tools/install_sandbox/targets/install_target_selection.py"),
}


@pytest.mark.parametrize(
    ("entrypoint_name", "command", "expected_text"),
    [
        (
            "host_runner",
            [sys.executable, "tools/install_sandbox/run.py", "--help"],
            "Run Graphify install scenarios in an isolated Docker sandbox.",
        ),
        (
            "sandbox_runner_file",
            [sys.executable, "tools/install_sandbox/sandbox_runner.py", "--help"],
            "In-container Graphify install scenario runner.",
        ),
        (
            "sandbox_runner_module",
            [sys.executable, "-m", "tools.install_sandbox.sandbox_runner", "--help"],
            "In-container Graphify install scenario runner.",
        ),
        (
            "reporting_agent_summary_file",
            [sys.executable, "tools/install_sandbox/reporting/agent_summary.py", "--help"],
            "Summarize Graphify install sandbox artifacts",
        ),
        (
            "reporting_agent_summary_module",
            [sys.executable, "-m", "tools.install_sandbox.reporting.agent_summary", "--help"],
            "Summarize Graphify install sandbox artifacts",
        ),
    ],
)
def test_supported_direct_entrypoint_help_contracts(entrypoint_name: str, command: list[str], expected_text: str) -> None:
    assert entrypoint_name in SUPPORTED_DIRECT_ENTRYPOINTS

    result = subprocess.run(command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert expected_text in result.stdout


def test_supported_validation_plan_direct_import_contract() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'tools/install_sandbox'); "
            "from validation_plan import ValidationWorkItem, build_validation_plan; "
            "print(build_validation_plan.__name__, ValidationWorkItem.__name__)",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert SUPPORTED_DIRECT_ENTRYPOINTS["validation_plan_direct_import"] == Path("tools/install_sandbox/validation_plan.py")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "build_validation_plan ValidationWorkItem"


def test_non_entrypoint_fallbacks_are_cleanup_candidates_not_supported_contracts() -> None:
    supported_files = {
        path
        for path in SUPPORTED_DIRECT_ENTRYPOINTS.values()
        if isinstance(path, Path) and path != Path("tools/install_sandbox/validation_plan.py")
    }

    assert NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES.isdisjoint(supported_files)
    assert Path("tools/install_sandbox/reporting/agent_summary.py") not in NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES
    for relative_path in NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "except ImportError" in text or "except ModuleNotFoundError" in text


def test_runtime_reporting_owner_fallbacks_removed_from_cleanup_candidates() -> None:
    assert REMOVED_RUNTIME_REPORTING_FALLBACKS.isdisjoint(NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES)
    for relative_path in REMOVED_RUNTIME_REPORTING_FALLBACKS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "except ImportError" not in text
        assert "direct script import fallback" not in text
        assert "from tools.install_sandbox" not in text


def test_registry_target_owner_fallbacks_removed_from_cleanup_candidates() -> None:
    assert REMOVED_REGISTRY_TARGET_FALLBACKS.isdisjoint(NON_ENTRYPOINT_FALLBACK_CLEANUP_CANDIDATES)
    for relative_path in REMOVED_REGISTRY_TARGET_FALLBACKS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "direct script import fallback" not in text
        assert "from tools.install_sandbox" not in text
