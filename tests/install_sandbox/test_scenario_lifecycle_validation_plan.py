from __future__ import annotations

from tools.install_sandbox.lifecycle import scenario_lifecycle_plan, scenario_lifecycle_support
from tools.install_sandbox.targets.install_target_defaults import DEFAULT_SCENARIO_REGISTRY
from tools.install_sandbox.targets.install_target_models import (
    DisposableArtifactScenarioSpec,
    DisposableSeedFile,
    SelectedUniversalUninstallScenario,
    UniversalUninstallScenarioSpec,
)
from tests.install_sandbox.scenario_lifecycle_test_support import (
    HookFactory,
    command_artifact_dir,
    make_disposable_graphify_out_spec,
    make_scenario,
    make_universal_uninstall_selection,
    make_validation_plan,
)


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

    results = scenario_lifecycle_plan.run_validation_plan(
        plan,
        env,
        hooks=factory.hooks(
            matrix_overrides=scenario_lifecycle_support.MatrixRunnerOverrides(
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
        universal_uninstall=(SelectedUniversalUninstallScenario(universal_spec, (first, second)),),
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

    results = scenario_lifecycle_plan.run_validation_plan(
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

    results = scenario_lifecycle_plan.run_validation_plan(
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
            SelectedUniversalUninstallScenario(user_spec, (make_scenario("first", "user"), make_scenario("second", "user"))),
            SelectedUniversalUninstallScenario(project_spec, (first, second)),
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

    results = scenario_lifecycle_plan.run_validation_plan(
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
        universal_uninstall=(SelectedUniversalUninstallScenario(universal_spec, (first, second)),),
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

    results = scenario_lifecycle_plan.run_validation_plan(
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
        universal_uninstall=(SelectedUniversalUninstallScenario(universal_spec, (scenario,)),),
    )

    results = scenario_lifecycle_plan.run_validation_plan(
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

    results = scenario_lifecycle_plan.run_validation_plan(
        plan,
        {},
        hooks=factory.hooks(
            run_scenario_func=run_scenario,
            run_disposable_artifact_scenario_func=run_disposable,
        ),
    )

    assert calls == ["scenario:arbitrary:user", "disposable:user-disposable-cleanup"]
    assert [result["id"] for result in results] == ["arbitrary-user", "user-disposable-cleanup"]
