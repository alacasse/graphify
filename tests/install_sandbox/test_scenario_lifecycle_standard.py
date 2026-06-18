from __future__ import annotations

import json

from tools.install_sandbox import scenario_lifecycle

from tests.install_sandbox.scenario_lifecycle_test_support import (
    STANDARD_ARTIFACT_FILENAMES,
    HookFactory,
    artifact_names,
    assert_preserved_result_shape,
    command_artifact_dir,
    make_scenario,
)


# Lifecycle tests depend on the ScenarioFileEffects protocol. Direct Installer
# Core decisions live in test_install_surface_core*.py topic modules; the
# concrete adapter boundary lives in test_file_effects_adapter.py.


def test_scenario_file_effects_protocol_omits_oracle_and_core_leaf_helpers() -> None:
    lifecycle_methods = set(scenario_lifecycle.ScenarioFileEffects.__dict__)

    assert not {
        "assert_expected_files",
        "assert_scope_boundaries",
        "assert_no_unexpected_graphify_files",
        "assert_idempotent_state",
        "assert_installed_skill_sidecars",
        "expected_generated_relative_keys",
        "check_record",
    } & lifecycle_methods


def test_run_scenario_skips_followups_when_initial_install_fails(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [1]
    scenario = make_scenario()

    result = scenario_lifecycle.run_scenario(scenario, {}, hooks=factory.hooks())
    artifact_dir = factory.output / "scenarios" / "codex-project"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert factory.calls.count("command:graphify install --platform codex") == 1
    assert not any(call.startswith("command:graphify uninstall") for call in factory.calls)
    assert "seed-stale:codex" not in factory.calls
    assert "sidecars:codex" not in factory.calls
    assert "equivalence:codex" not in factory.calls
    assert result["passed"] is False
    assert assertions["repeat_install_exit_code"] is None
    assert assertions["stale_sidecar_repair_exit_code"] is None
    assert assertions["stale_sidecar_repair_seeded"] == []
    assert assertions["uninstall_exit_code"] is None
    assert "before-install-files.json" in artifact_names(artifact_dir)
    assert "after-install-files.json" in artifact_names(artifact_dir)
    assert "after-repeat-install-files.json" not in artifact_names(artifact_dir)
    assert "after-stale-sidecar-repair-files.json" not in artifact_names(artifact_dir)
    assert "after-uninstall-files.json" not in artifact_names(artifact_dir)


def test_run_scenario_preserves_stage_order_and_records_followups(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0, 0, 0, 0]
    factory.seeded_sidecars = [{"ok": True, "detail": "seeded_stale_reference_fragment"}]
    scenario = make_scenario()

    result = scenario_lifecycle.run_scenario(scenario, {}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "codex-project" / "assertions.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["passed"] is True
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert command_artifact_dir(result) == str(factory.output / "scenarios" / "codex-project")
    assert factory.command_artifact_dirs == [factory.output / "scenarios" / "codex-project"]
    assert "target_runtime_verification" not in result
    assert assertions["install_exit_code"] == 0
    assert assertions["repeat_install_exit_code"] == 0
    assert assertions["stale_sidecar_repair_exit_code"] == 0
    assert assertions["uninstall_exit_code"] == 0
    assert [call for call in factory.calls if call.startswith("command:")] == [
        "command:graphify install --platform codex",
        "command:graphify install --platform codex",
        "command:graphify install --platform codex",
        "command:graphify uninstall --platform codex",
    ]
    assert factory.calls == [
        "reset",
        "seed:codex",
        "manifest:before-install-files.json",
        "command:graphify install --platform codex",
        "state:codex",
        "expected:codex",
        "scope:codex",
        "unexpected:install",
        "manifest:after-install-files.json",
        "copy:codex",
        "command:graphify install --platform codex",
        "state:codex",
        "idempotent",
        "unexpected:repeat_install",
        "manifest:after-repeat-install-files.json",
        "seed-stale:codex",
        "command:graphify install --platform codex",
        "sidecars:codex",
        "unexpected:stale_sidecar_repair",
        "manifest:after-stale-sidecar-repair-files.json",
        "command:graphify uninstall --platform codex",
        "uninstalled:codex",
        "unexpected:uninstall",
        "manifest:after-uninstall-files.json",
        "equivalence:codex",
    ]


def test_run_scenario_preserves_standard_artifact_filenames(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0, 0, 0, 0]
    factory.seeded_sidecars = [{"ok": True, "detail": "seeded_stale_reference_fragment"}]

    scenario_lifecycle.run_scenario(make_scenario(), {}, hooks=factory.hooks())

    artifact_dir = factory.output / "scenarios" / "codex-project"
    assert STANDARD_ARTIFACT_FILENAMES <= artifact_names(artifact_dir)
