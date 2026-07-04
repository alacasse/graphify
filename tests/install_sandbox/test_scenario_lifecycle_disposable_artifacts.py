from __future__ import annotations

import json

from tools.install_sandbox.lifecycle import scenario_lifecycle_disposable
from tools.install_sandbox.targets.install_target_models import DisposableArtifactScenarioSpec, DisposableSeedFile
from tests.install_sandbox.scenario_lifecycle_test_support import (
    HookFactory,
    artifact_names,
    assert_preserved_result_shape,
    command_artifact_dir,
    make_disposable_graphify_out_spec,
)


def test_purge_scenario_removes_disposable_graphify_out_and_writes_artifacts(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    spec = make_disposable_graphify_out_spec()

    def purge_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        result = factory.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class=command_class, timeout_seconds=timeout_seconds)
        graphify_out = factory.project / "graphify-out"
        assert (graphify_out / "graph.json").exists()
        factory.calls.append("graphify-out:present-before-purge")
        if graphify_out.exists():
            for child in graphify_out.iterdir():
                child.unlink()
            graphify_out.rmdir()
        return result

    result = scenario_lifecycle_disposable.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks(run_capture=purge_run_capture))
    purge_scenario_id = spec.scenario_id
    artifact_dir = factory.output / "scenarios" / purge_scenario_id
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["id"] == purge_scenario_id
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert result["target"] == "purge"
    assert "platform" not in result
    assert command_artifact_dir(result) == str(artifact_dir / "uninstall-purge")
    assert factory.command_artifact_dirs == [artifact_dir / "uninstall-purge"]
    assert "target_runtime_verification" not in result
    assert assertions["scenario"] == {"id": purge_scenario_id, "scope": "project", "target": "purge"}
    assert assertions["uninstall_exit_code"] == 0
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": True, "detail": "purged"}]
    assert risks["statuses"] == ["graphify_install_verified"]
    assert not (factory.project / "graphify-out").exists()
    assert {"before-install-files.json", "after-uninstall-files.json", "assertions.json", "risk.json"} <= artifact_names(artifact_dir)
    assert [record["filename"] for record in factory.manifest_records] == ["before-install-files.json", "after-uninstall-files.json"]
    assert factory.manifest_records[0]["kwargs"] == {}
    assert factory.manifest_records[1]["kwargs"] == {}
    assert factory.captured_artifact_dirs == [artifact_dir / "uninstall-purge"]
    assert factory.command_records == [
        {
            "command": ("graphify", "uninstall", "--purge"),
            "cwd": factory.project,
            "artifact_dir": artifact_dir / "uninstall-purge",
            "command_class": "installer",
            "timeout_seconds": None,
        }
    ]
    assert factory.calls == [
        "reset",
        "manifest:before-install-files.json",
        "command:graphify uninstall --purge",
        "graphify-out:present-before-purge",
        "manifest:after-uninstall-files.json",
        "disposable-check:graphify-out",
    ]


def test_purge_scenario_derives_failure_from_command_exit_and_removal(tmp_path) -> None:
    spec = make_disposable_graphify_out_spec()
    factory = HookFactory(tmp_path / "command-fails")
    factory.command_results = [1]

    def failing_purge_removes_graph(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        result = factory.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class=command_class, timeout_seconds=timeout_seconds)
        graphify_out = factory.project / "graphify-out"
        for child in graphify_out.iterdir():
            child.unlink()
        graphify_out.rmdir()
        return result

    result = scenario_lifecycle_disposable.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks(run_capture=failing_purge_removes_graph))
    assertions = json.loads((factory.output / "scenarios" / spec.scenario_id / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 1
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": True, "detail": "purged"}]

    factory = HookFactory(tmp_path / "graph-remains")
    factory.command_results = [0]
    result = scenario_lifecycle_disposable.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / spec.scenario_id / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 0
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": False, "detail": "still_exists"}]


def test_purge_scenario_derives_failure_from_emitted_check_records(tmp_path) -> None:
    spec = make_disposable_graphify_out_spec()
    factory = HookFactory(tmp_path)
    default_hooks = factory.hooks()

    class FailingDisposableChecks:
        def __getattr__(self, name):
            return getattr(default_hooks.file_effects, name)

        def disposable_artifact_checks(self, disposable_path, removed):
            factory.calls.append("disposable-check:forced-failure")
            return [{"path": str(disposable_path), "ok": False, "detail": "forced_failure"}]

    def purge_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        result = factory.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class=command_class, timeout_seconds=timeout_seconds)
        graphify_out = factory.project / "graphify-out"
        for child in graphify_out.iterdir():
            child.unlink()
        graphify_out.rmdir()
        return result

    result = scenario_lifecycle_disposable.run_disposable_artifact_scenario(
        spec,
        {},
        hooks=factory.hooks(file_effects=FailingDisposableChecks(), run_capture=purge_run_capture),
    )
    artifact_dir = factory.output / "scenarios" / spec.scenario_id
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["passed"] is False
    assert result["graphify_file_effects_passed"] is False
    assert result["overall_status"] == "graphify_install_failed"
    assert result["risks"] == ["graphify_install_failed"]
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 0
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": False, "detail": "forced_failure"}]
    assert risks["statuses"] == ["graphify_install_failed"]
    assert not (factory.project / "graphify-out").exists()


def test_disposable_artifact_lifecycle_uses_declared_seed_path_command_cwd_and_artifact(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    undeclared_path = factory.project / "graphify-out"
    undeclared_path.mkdir()
    (undeclared_path / "graph.json").write_text("{}\n", encoding="utf-8")
    spec = DisposableArtifactScenarioSpec(
        scenario_id="discard-weird-cache",
        synthetic_result_label="janitor",
        scope="workspace",
        command=("janitor", "discard", "cache"),
        cwd_root="home",
        artifact_subdir="declared-discard",
        disposable_path_root="user_cwd",
        disposable_path_relative="nested/cache-dir",
        seed_files=(DisposableSeedFile("token.txt", "seeded\n"),),
        scope_eligibility=("user",),
        risk_note="declared disposable path risk",
    )

    def discard_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        disposable_path = factory.user_cwd / "nested/cache-dir"
        assert (disposable_path / "token.txt").read_text(encoding="utf-8") == "seeded\n"
        result = factory.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class=command_class, timeout_seconds=timeout_seconds)
        (disposable_path / "token.txt").unlink()
        disposable_path.rmdir()
        return result

    result = scenario_lifecycle_disposable.run_disposable_artifact_scenario(
        spec,
        {},
        hooks=factory.hooks(run_capture=discard_run_capture),
    )
    artifact_dir = factory.output / "scenarios" / "discard-weird-cache"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert result["id"] == "discard-weird-cache"
    assert result["target"] == "janitor"
    assert "platform" not in result
    assert result["scope"] == "workspace"
    assert command_artifact_dir(result) == str(artifact_dir / "declared-discard")
    assert factory.command_records == [
        {
            "command": ("janitor", "discard", "cache"),
            "cwd": factory.home,
            "artifact_dir": artifact_dir / "declared-discard",
            "command_class": "installer",
            "timeout_seconds": None,
        }
    ]
    assert assertions["scenario"] == {"id": "discard-weird-cache", "scope": "workspace", "target": "janitor"}
    assert assertions["checks"] == [{"path": str(factory.user_cwd / "nested/cache-dir"), "ok": True, "detail": "purged"}]
    assert risks["notes"] == ["declared disposable path risk"]
    assert undeclared_path.exists()


def test_legacy_purge_wrapper_is_absent() -> None:
    assert not hasattr(scenario_lifecycle_disposable, "run_" + "purge_scenario")
