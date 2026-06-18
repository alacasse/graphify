from __future__ import annotations

import json

from tools.install_sandbox import scenario_lifecycle
from tools.install_sandbox.platform_specs import (
    DEFAULT_SCENARIO_REGISTRY,
    DisposableArtifactScenarioSpec,
    DisposableSeedFile,
    UniversalUninstallScenarioSpec,
)
from tests.install_sandbox.scenario_lifecycle_test_support import (
    HookFactory,
    artifact_names,
    assert_preserved_result_shape,
    command_artifact_dir,
    make_disposable_graphify_out_spec,
    make_scenario,
    make_universal_uninstall_selection,
    make_validation_plan,
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

    result = scenario_lifecycle.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks(run_capture=purge_run_capture))
    purge_scenario_id = spec.scenario_id
    artifact_dir = factory.output / "scenarios" / purge_scenario_id
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["id"] == purge_scenario_id
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert command_artifact_dir(result) == str(artifact_dir / "uninstall-purge")
    assert factory.command_artifact_dirs == [artifact_dir / "uninstall-purge"]
    assert "target_runtime_verification" not in result
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

    result = scenario_lifecycle.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks(run_capture=failing_purge_removes_graph))
    assertions = json.loads((factory.output / "scenarios" / spec.scenario_id / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 1
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": True, "detail": "purged"}]

    factory = HookFactory(tmp_path / "graph-remains")
    factory.command_results = [0]
    result = scenario_lifecycle.run_disposable_artifact_scenario(spec, {}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / spec.scenario_id / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 0
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": False, "detail": "still_exists"}]


def test_disposable_artifact_lifecycle_uses_declared_seed_path_command_cwd_and_artifact(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    undeclared_path = factory.project / "graphify-out"
    undeclared_path.mkdir()
    (undeclared_path / "graph.json").write_text("{}\n", encoding="utf-8")
    spec = DisposableArtifactScenarioSpec(
        scenario_id="discard-weird-cache",
        platform_label="janitor",
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

    result = scenario_lifecycle.run_disposable_artifact_scenario(
        spec,
        {},
        hooks=factory.hooks(run_capture=discard_run_capture),
    )
    artifact_dir = factory.output / "scenarios" / "discard-weird-cache"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert result["id"] == "discard-weird-cache"
    assert result["platform"] == "janitor"
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
    assert assertions["checks"] == [{"path": str(factory.user_cwd / "nested/cache-dir"), "ok": True, "detail": "purged"}]
    assert risks["notes"] == ["declared disposable path risk"]
    assert undeclared_path.exists()


def test_run_purge_scenario_preserves_legacy_wrapper(tmp_path, monkeypatch) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    env = {"HOME": str(factory.home)}
    first = make_disposable_graphify_out_spec()
    second = DisposableArtifactScenarioSpec(
        scenario_id="secondary-disposable",
        platform_label="purge",
        scope="project",
        command=("cleanup", "secondary"),
        cwd_root="project",
        artifact_subdir="secondary",
        disposable_path_root="project",
        disposable_path_relative="secondary",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="secondary cleanup",
    )
    calls: list[tuple[str, object]] = []

    def disposable_specs(scope, *, hooks):
        calls.append(("select", scope, hooks))
        return [first, second]

    class FakeDisposableArtifactLifecycle:
        def __init__(self, spec_arg, env_arg, hooks_arg) -> None:
            calls.append(("lifecycle", spec_arg, env_arg, hooks_arg))

        def run(self):
            calls.append(("run",))
            return {"id": first.scenario_id, "passed": True}

    monkeypatch.setattr(scenario_lifecycle, "disposable_artifact_scenarios", disposable_specs)
    monkeypatch.setattr(scenario_lifecycle, "DisposableArtifactLifecycle", FakeDisposableArtifactLifecycle)

    result = scenario_lifecycle.run_purge_scenario(env, hooks=hooks)

    assert result == {"id": "purge-disposable-graphify-out", "passed": True}
    assert calls == [
        ("select", "project", hooks),
        ("lifecycle", first, env, hooks),
        ("run",),
    ]


def test_run_matrix_scenarios_delegates_to_planner_and_runs_plan_once(tmp_path, monkeypatch) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    env = {"HOME": str(factory.home)}
    plan = make_validation_plan(platforms=("first", "second"), scope="project")
    calls: list[tuple[str, object]] = []

    def build_plan(registry, *, all_platforms, platform_name=None, selected_platform_names=None, scope="both", **kwargs):
        calls.append(("build", registry, all_platforms, platform_name, tuple(selected_platform_names), scope, kwargs))
        return plan

    def run_plan(plan_arg, env_arg, hooks_arg, fail_fast_scenarios=False):
        calls.append(("run", plan_arg, env_arg, hooks_arg, fail_fast_scenarios))
        return [{"id": "sentinel", "passed": True}]

    monkeypatch.setattr(scenario_lifecycle.validation_plan, "build_validation_plan", build_plan)
    monkeypatch.setattr(scenario_lifecycle, "run_validation_plan", run_plan)

    results = scenario_lifecycle.run_matrix_scenarios(
        ["first", "second"],
        "project",
        env,
        hooks=hooks,
        fail_fast_scenarios=True,
    )

    assert results == [{"id": "sentinel", "passed": True}]
    assert calls == [
        ("build", hooks.scenario_registry, False, None, ("first", "second"), "project", {}),
        ("run", plan, env, hooks, True),
    ]


def test_run_validation_plan_preserves_matrix_runner_overrides(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    env = {"HOME": str(factory.home)}
    calls: list[str] = []
    first = make_scenario("first", "project", uninstall=False)
    second = make_scenario("second", "project", uninstall=False)
    disposable_spec = make_disposable_graphify_out_spec()
    plan = make_validation_plan(
        platforms=("second", "first"),
        scope="project",
        standard_scenarios=(second, first),
        universal_uninstall=(make_universal_uninstall_selection((second, first)),),
        disposable_artifacts=(disposable_spec,),
    )

    def run_scenario(item, scenario_env):
        calls.append(f"scenario:{item.platform}:{item.scope}:{scenario_env['HOME']}")
        return {
            "id": f"{item.platform}-{item.scope}",
            "platform": item.platform,
            "scope": item.scope,
            "passed": True,
        }

    def run_universal(selected, scenario_env):
        scenario_platforms = ",".join(scenario.platform for scenario in selected.installed_scenarios)
        calls.append(f"universal:{selected.spec.scope}:{scenario_platforms}:{scenario_env['HOME']}")
        return {
            "id": f"universal-{selected.spec.scope}",
            "platform": selected.spec.platform_label,
            "scope": selected.spec.scope,
            "passed": True,
        }

    def run_disposable(spec, scenario_env):
        calls.append(f"disposable:{spec.scenario_id}:{scenario_env['HOME']}")
        return {
            "id": spec.scenario_id,
            "platform": spec.platform_label,
            "scope": spec.scope,
            "passed": True,
        }

    results = scenario_lifecycle.run_validation_plan(
        plan,
        env,
        hooks=factory.hooks(
            matrix_overrides=scenario_lifecycle.MatrixRunnerOverrides(
                run_scenario=run_scenario,
                run_universal_uninstall_scenario=run_universal,
                run_disposable_artifact_scenario=run_disposable,
            ),
        ),
    )

    assert calls == [
        f"scenario:second:project:{factory.home}",
        f"scenario:first:project:{factory.home}",
        f"universal:project:second,first:{factory.home}",
        f"disposable:purge-disposable-graphify-out:{factory.home}",
    ]
    assert [result["id"] for result in results] == [
        "second-project",
        "first-project",
        "universal-project",
        "purge-disposable-graphify-out",
    ]


def test_run_validation_plan_collects_graphify_failures_and_skips_synthetics(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []
    first = make_scenario("first", "project", uninstall=False)
    second = make_scenario("second", "project", uninstall=False)
    universal_spec = UniversalUninstallScenarioSpec(
        scenario_id="project-sweep",
        platform_label="multiple",
        scope="project",
        command=("cleanup", "project"),
        cwd_root="project",
        eligible_platform_scope="project",
    )
    disposable_spec = DisposableArtifactScenarioSpec(
        scenario_id="purge-project-cache",
        platform_label="purge",
        scope="project",
        command=("purge", "project"),
        cwd_root="project",
        artifact_subdir="purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="project cleanup",
    )
    plan = make_validation_plan(
        platforms=("first", "second"),
        scope="project",
        standard_scenarios=(first, second),
        universal_uninstall=(scenario_lifecycle.SelectedUniversalUninstallScenario(universal_spec, (first, second)),),
        disposable_artifacts=(disposable_spec,),
    )

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {
            "id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope),
            "platform": item.platform,
            "scope": item.scope,
            "passed": item.platform == "second",
            "graphify_file_effects_passed": item.platform == "second",
        }

    def unexpected_synthetic(*args, **kwargs):
        raise AssertionError("synthetic scenarios should not run after a Graphify install failure")

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
            run_universal_uninstall_scenario_func=unexpected_synthetic,
            run_purge_scenario_func=unexpected_synthetic,
        ),
    )

    assert calls == ["scenario:first", "scenario:second"]
    assert [result["passed"] for result in results] == [False, True]


def test_run_validation_plan_fail_fast_stops_first_graphify_failure(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []
    plan = make_validation_plan(
        platforms=("first", "second"),
        scope="project",
        standard_scenarios=(
            make_scenario("first", "project", uninstall=False),
            make_scenario("second", "project", uninstall=False),
        ),
    )

    def run_scenario(item, env):
        calls.append(item.platform)
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": False}

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
        ),
        fail_fast_scenarios=True,
    )

    assert calls == ["first"]
    assert len(results) == 1
    assert results[0]["passed"] is False


def test_run_validation_plan_collects_universal_failures_and_runs_disposable_cleanup(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []
    first = make_scenario("first", "project", uninstall=False)
    second = make_scenario("second", "project", uninstall=False)
    user_spec = UniversalUninstallScenarioSpec(
        scenario_id="universal-uninstall-user",
        platform_label="multiple",
        scope="user",
        command=("graphify", "uninstall"),
        cwd_root="user_cwd",
        eligible_platform_scope="user",
    )
    project_spec = UniversalUninstallScenarioSpec(
        scenario_id="universal-uninstall-project",
        platform_label="multiple",
        scope="project",
        command=("graphify", "uninstall", "--project"),
        cwd_root="project",
        eligible_platform_scope="project",
    )
    disposable_spec = DisposableArtifactScenarioSpec(
        scenario_id=DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id(),
        platform_label="purge",
        scope="project",
        command=("graphify", "uninstall", "--purge"),
        cwd_root="project",
        artifact_subdir="uninstall-purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="purge verified only against disposable sandbox graphify-out state",
    )
    plan = make_validation_plan(
        platforms=("first", "second"),
        scope="both",
        standard_scenarios=(first, second),
        universal_uninstall=(
            scenario_lifecycle.SelectedUniversalUninstallScenario(user_spec, (make_scenario("first", "user"), make_scenario("second", "user"))),
            scenario_lifecycle.SelectedUniversalUninstallScenario(project_spec, (first, second)),
        ),
        disposable_artifacts=(disposable_spec,),
    )

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": True}

    def run_universal(selected, env):
        calls.append(f"universal:{selected.spec.scope}")
        return {
            "id": selected.spec.scenario_id,
            "platform": selected.spec.platform_label,
            "scope": selected.spec.scope,
            "passed": False,
        }

    def run_purge(spec, env):
        calls.append("purge")
        return {"id": spec.scenario_id, "platform": spec.platform_label, "scope": spec.scope, "passed": False}

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
            run_universal_uninstall_scenario_func=run_universal,
            run_purge_scenario_func=run_purge,
        ),
    )

    assert calls == ["scenario:first", "scenario:second", "universal:user", "universal:project", "purge"]
    assert [result["id"] for result in results][-3:] == [
        DEFAULT_SCENARIO_REGISTRY.universal_uninstall_scenario_id("user"),
        DEFAULT_SCENARIO_REGISTRY.universal_uninstall_scenario_id("project"),
        DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id(),
    ]


def test_run_validation_plan_preserves_legacy_matrix_runner_override_shapes(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []
    first = make_scenario("first", "project", uninstall=False)
    second = make_scenario("second", "project", uninstall=False)
    universal_spec = UniversalUninstallScenarioSpec(
        scenario_id="legacy-project-sweep",
        platform_label="multiple",
        scope="project",
        command=("cleanup", "project"),
        cwd_root="project",
        eligible_platform_scope="project",
    )
    disposable_spec = DisposableArtifactScenarioSpec(
        scenario_id="legacy-purge",
        platform_label="purge",
        scope="project",
        command=("purge",),
        cwd_root="project",
        artifact_subdir="purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="legacy cleanup",
    )
    plan = make_validation_plan(
        platforms=("first", "second"),
        scope="project",
        standard_scenarios=(first, second),
        universal_uninstall=(scenario_lifecycle.SelectedUniversalUninstallScenario(universal_spec, (first, second)),),
        disposable_artifacts=(disposable_spec,),
    )

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {"id": f"{item.platform}-{item.scope}", "platform": item.platform, "scope": item.scope, "passed": True}

    def run_universal(universal_scope, scenarios, env):
        calls.append(f"universal:{universal_scope}:{','.join(scenario.platform for scenario in scenarios)}")
        return {"id": universal_spec.scenario_id, "platform": universal_spec.platform_label, "scope": universal_scope, "passed": True}

    def run_purge(env):
        calls.append("purge")
        return {"id": disposable_spec.scenario_id, "platform": disposable_spec.platform_label, "scope": disposable_spec.scope, "passed": True}

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
            run_universal_uninstall_scenario_func=run_universal,
            run_purge_scenario_func=run_purge,
        ),
    )

    assert calls == ["scenario:first", "scenario:second", "universal:project:first,second", "purge"]
    assert [result["id"] for result in results] == ["first-project", "second-project", "legacy-project-sweep", "legacy-purge"]


def test_run_validation_plan_preserves_selected_universal_uninstall_spec(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    factory.command_results = [0]
    scenario = make_scenario("arbitrary", "project", uninstall=False)
    universal_spec = UniversalUninstallScenarioSpec(
        scenario_id="selected-sweep",
        platform_label="selected-cleaner",
        scope="selected-scope",
        command=("selected", "remove"),
        cwd_root="user_cwd",
        eligible_platform_scope="project",
        artifact_subdir="selected-artifacts",
        risk_note="selected risk note",
    )

    def run_scenario(item, env):
        return {"id": "arbitrary-project", "platform": item.platform, "scope": item.scope, "passed": True, "graphify_file_effects_passed": True}

    plan = make_validation_plan(
        platforms=("arbitrary",),
        scope="project",
        standard_scenarios=(scenario,),
        universal_uninstall=(scenario_lifecycle.SelectedUniversalUninstallScenario(universal_spec, (scenario,)),),
    )

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
        ),
    )

    artifact_dir = factory.output / "scenarios" / "selected-sweep"
    assert results[-1]["id"] == "selected-sweep"
    assert results[-1]["platform"] == "selected-cleaner"
    assert results[-1]["scope"] == "selected-scope"
    assert command_artifact_dir(results[-1]) == str(artifact_dir / "selected-artifacts")
    assert factory.command_records[-1]["command"] == ("selected", "remove")
    assert factory.command_records[-1]["cwd"] == factory.user_cwd


def test_run_validation_plan_runs_declared_disposable_scenarios_without_scope_branching(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []
    scenario = make_scenario("arbitrary", "user", uninstall=False)
    disposable_spec = DisposableArtifactScenarioSpec(
        scenario_id="user-disposable-cleanup",
        platform_label="cleanup",
        scope="user",
        command=("cleanup", "now"),
        cwd_root="home",
        artifact_subdir="cleanup-artifacts",
        disposable_path_root="home",
        disposable_path_relative="tmp/cache",
        seed_files=(DisposableSeedFile("item.txt", "x"),),
        scope_eligibility=("user",),
        risk_note="user-scope disposable cleanup",
    )
    plan = make_validation_plan(
        platforms=("arbitrary",),
        scope="user",
        standard_scenarios=(scenario,),
        disposable_artifacts=(disposable_spec,),
    )

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}:{item.scope}")
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": True}

    def run_disposable(spec, env):
        calls.append(f"disposable:{spec.scenario_id}")
        return {"id": spec.scenario_id, "platform": spec.platform_label, "scope": spec.scope, "passed": True}

    results = scenario_lifecycle.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
            run_disposable_artifact_scenario_func=run_disposable,
        ),
    )

    assert calls == ["scenario:arbitrary:user", "disposable:user-disposable-cleanup"]
    assert [result["id"] for result in results] == ["arbitrary-user", "user-disposable-cleanup"]
