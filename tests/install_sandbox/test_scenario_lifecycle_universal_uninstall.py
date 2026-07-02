from __future__ import annotations

import json

from tools.install_sandbox.lifecycle import scenario_lifecycle_support, scenario_lifecycle_universal
from tests.install_sandbox.scenario_lifecycle_test_support import (
    HookFactory,
    artifact_names,
    assert_preserved_result_shape,
    command_artifact_dir,
    make_scenario,
    make_universal_uninstall_selection,
)


def test_universal_uninstall_scenario_writes_assertions_and_risk_artifacts(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    scenarios = (make_scenario("first", "project"), make_scenario("second", "project"))
    selected = make_universal_uninstall_selection(scenarios)

    result = scenario_lifecycle_universal.run_universal_uninstall_scenario(selected, env={}, hooks=hooks)
    artifact_dir = factory.output / "scenarios" / "universal-uninstall-project"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["id"] == "universal-uninstall-project"
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert command_artifact_dir(result) == str(artifact_dir / "uninstall")
    assert factory.command_artifact_dirs == [artifact_dir / "uninstall"]
    assert "target_runtime_verification" not in result
    assert assertions["uninstall_command"] == ["graphify", "uninstall", "--project"]
    assert assertions["uninstall_exit_code"] == 0
    assert [item["scenario_id"] for item in assertions["install_results"]] == ["first-project", "second-project"]
    assert risks["statuses"] == ["graphify_install_verified"]
    assert "target_runtime_verification" not in result
    assert {"before-install-files.json", "after-install-files.json", "after-uninstall-files.json", "assertions.json", "risk.json"} <= artifact_names(artifact_dir)
    assert [record["filename"] for record in factory.manifest_records] == [
        "before-install-files.json",
        "after-install-files.json",
        "after-uninstall-files.json",
    ]
    assert factory.manifest_records[0]["kwargs"] == {}
    assert factory.manifest_records[1]["kwargs"] == {"debug_full": True}
    assert factory.manifest_records[2]["kwargs"] == {"debug_full": True}
    assert factory.captured_artifact_dirs == [
        artifact_dir / "installs" / "first-project",
        artifact_dir / "installs" / "second-project",
        artifact_dir / "uninstall",
    ]
    assert factory.command_records[-1]["cwd"] == factory.project
    assert factory.calls == [
        "reset",
        "seed:first",
        "seed:second",
        "manifest:before-install-files.json",
        "command:graphify install --platform first",
        "expected:first",
        "scope:first",
        "command:graphify install --platform second",
        "expected:second",
        "scope:second",
        "manifest:after-install-files.json",
        "command:graphify uninstall --project",
        "universal-uninstalled:first",
        "universal-uninstalled:second",
        "unexpected:universal_uninstall",
        "manifest:after-uninstall-files.json",
    ]


def test_universal_uninstall_scenario_derives_failure_from_installs_uninstall_and_checks(tmp_path) -> None:
    scenarios = (make_scenario("first", "project"), make_scenario("second", "project"))
    selected = make_universal_uninstall_selection(scenarios)

    factory = HookFactory(tmp_path / "install-fails")
    factory.command_results = [1, 0, 0]
    result = scenario_lifecycle_universal.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "universal-uninstall-project" / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert [item["exit_code"] for item in assertions["install_results"]] == [1, 0]

    factory = HookFactory(tmp_path / "uninstall-fails")
    factory.command_results = [0, 0, 1]
    result = scenario_lifecycle_universal.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "universal-uninstall-project" / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 1

    factory = HookFactory(tmp_path / "checks-fail")
    factory.command_results = [0, 0, 0]
    factory.universal_check_ok = False
    result = scenario_lifecycle_universal.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "universal-uninstall-project" / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert {check["detail"] for check in assertions["checks"]} >= {"universal_uninstall_failed"}


def test_universal_uninstall_lifecycle_uses_declared_command_cwd_platform_and_risk(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0, 0, 0]
    scenarios = (make_scenario("alpha", "project"), make_scenario("beta", "project"))
    selected = make_universal_uninstall_selection(
        scenarios,
        scenario_id="sweep-custom-workspace",
        platform_label="synthetic-cleaner",
        scope="workspace",
        command=("custom-tool", "remove", "workspace"),
        cwd_root="user_cwd",
        eligible_target_scope="unused-scope",
        artifact_subdir="declared-artifacts",
        risk_note="declared lifecycle risk",
    )

    result = scenario_lifecycle_universal.run_universal_uninstall_scenario(
        selected,
        env={},
        hooks=factory.hooks(),
    )
    artifact_dir = factory.output / "scenarios" / "sweep-custom-workspace"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert result["id"] == "sweep-custom-workspace"
    assert result["target"] == "synthetic-cleaner"
    assert "platform" not in result
    assert result["scope"] == "workspace"
    assert command_artifact_dir(result) == str(artifact_dir / "declared-artifacts")
    assert assertions["scenario"] == {
        "id": "sweep-custom-workspace",
        "scope": "workspace",
        "targets": ["alpha", "beta"],
    }
    assert assertions["uninstall_command"] == ["custom-tool", "remove", "workspace"]
    assert factory.command_records[-1]["command"] == ("custom-tool", "remove", "workspace")
    assert factory.command_records[-1]["cwd"] == factory.user_cwd
    assert risks["notes"] == ["declared lifecycle risk"]


def test_run_universal_uninstall_scenario_has_no_scope_wrapper() -> None:
    assert scenario_lifecycle_universal.run_universal_uninstall_scenario.__code__.co_varnames[:2] == ("selected", "env")
