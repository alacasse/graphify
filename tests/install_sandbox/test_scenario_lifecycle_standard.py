from __future__ import annotations

import json

from tools.install_sandbox.lifecycle import scenario_lifecycle_standard, scenario_lifecycle_support

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
    lifecycle_methods = set(scenario_lifecycle_support.ScenarioFileEffects.__dict__)

    assert not {
        "assert_expected_files",
        "assert_scope_boundaries",
        "assert_no_unexpected_graphify_files",
        "assert_idempotent_state",
        "assert_installed_skill_sidecars",
        "expected_generated_relative_keys",
        "capture_state",
        "install_checks",
        "repeat_install_checks",
        "stale_sidecar_repair_checks",
        "uninstall_checks",
        "unexpected_checks",
        "check_record",
    } & lifecycle_methods
    assert not hasattr(scenario_lifecycle_support, "_standard_scenario_command_ok")


def test_run_scenario_skips_followups_when_initial_install_fails(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [1]
    scenario = make_scenario()

    result = scenario_lifecycle_standard.run_scenario(scenario, {}, hooks=factory.hooks())
    artifact_dir = factory.output / "scenarios" / "codex-project"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result, identity_key="target")
    assert factory.command_call_strings() == ["command:graphify install --platform codex"]
    assert factory.command_artifact_subdirs() == ["."]
    skipped_followups = {"seed-stale:codex", "sidecars:codex", "equivalence:codex"}
    assert not skipped_followups & set(factory.calls)
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

    result = scenario_lifecycle_standard.run_scenario(scenario, {}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "codex-project" / "assertions.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result, identity_key="target")
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
    assert factory.command_call_strings() == [
        "command:graphify install --platform codex",
        "command:graphify install --platform codex",
        "command:graphify install --platform codex",
        "command:graphify uninstall --platform codex",
    ]
    assert factory.command_artifact_subdirs() == [".", "repeat-install", "stale-sidecar-repair", "uninstall"]
    assert factory.command_record_index("repeat-install") < factory.call_index("idempotent")
    assert factory.call_index("idempotent") < factory.call_index("seed-stale:codex")
    assert factory.command_record_index("stale-sidecar-repair") < factory.call_index("sidecars:codex")
    assert factory.call_index("sidecars:codex") < factory.call_index("command:graphify uninstall --platform codex")
    assert factory.call_index("command:graphify uninstall --platform codex") < factory.call_index("equivalence:codex")
    assert {"detail": "unchanged_after_repeat_install", "ok": True} in assertions["checks"]
    assert {"detail": "sidecars", "ok": True} in assertions["stale_sidecar_repair_checks"]
    assert {"detail": "removed", "ok": True} in assertions["checks"]


def test_standard_lifecycle_execution_interface_records_observable_contract(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0, 0, 0, 0]
    factory.seeded_sidecars = [{"ok": True, "detail": "seeded_stale_reference_fragment"}]
    scenario = make_scenario()

    result = scenario_lifecycle_standard.StandardScenarioLifecycleExecutor(factory.hooks()).run(scenario, {})

    artifact_dir = factory.output / "scenarios" / "codex-project"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risk = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))
    command_artifact = result["command_artifact"]

    assert_preserved_result_shape(result, identity_key="target")
    assert result["id"] == assertions["scenario"]["id"] == "codex-project"
    assert result["target"] == assertions["scenario"]["target"] == "codex"
    assert "platform" not in result
    assert "platform" not in assertions["scenario"]
    assert result["scope"] == assertions["scenario"]["scope"] == "project"
    assert result["passed"] is assertions["passed"] is True
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert result["risks"] == risk["statuses"] == ["graphify_install_verified"]
    assert command_artifact == {
        "command": "graphify install",
        "transcript_path": "transcript.txt",
        "artifact_dir": str(artifact_dir),
    }
    assert STANDARD_ARTIFACT_FILENAMES <= artifact_names(artifact_dir)
    assert assertions["install_exit_code"] == 0
    assert assertions["repeat_install_exit_code"] == 0
    assert assertions["stale_sidecar_repair_exit_code"] == 0
    assert assertions["uninstall_exit_code"] == 0
    assert all(check["ok"] for check in assertions["checks"])


def test_run_scenario_preserves_standard_artifact_filenames(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0, 0, 0, 0]
    factory.seeded_sidecars = [{"ok": True, "detail": "seeded_stale_reference_fragment"}]

    scenario_lifecycle_standard.run_scenario(make_scenario(), {}, hooks=factory.hooks())

    artifact_dir = factory.output / "scenarios" / "codex-project"
    assert STANDARD_ARTIFACT_FILENAMES <= artifact_names(artifact_dir)
