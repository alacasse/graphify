from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.install_sandbox import scenario_lifecycle
from tools.install_sandbox.platform_specs import DEFAULT_SCENARIO_REGISTRY, ExpectedPath, Scenario


PRESERVED_RESULT_FIELDS = {
    "id",
    "platform",
    "scope",
    "passed",
    "graphify_file_effects_passed",
    "overall_status",
    "duration_ms",
    "command_artifact",
    "reproduction_command",
}

STANDARD_ARTIFACT_FILENAMES = {
    "before-install-files.json",
    "after-install-files.json",
    "after-repeat-install-files.json",
    "after-stale-sidecar-repair-files.json",
    "after-uninstall-files.json",
    "assertions.json",
    "risk.json",
}


def make_scenario(platform: str = "codex", scope: str = "project", *, uninstall: bool = True) -> Scenario:
    return Scenario(
        platform=platform,
        scope=scope,
        install_command=("graphify", "install", "--platform", platform),
        uninstall_command=("graphify", "uninstall", "--platform", platform) if uninstall else None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=(ExpectedPath("project" if scope == "project" else "home", f"{platform}-{scope}.md"),),
    )


class HookFactory:
    def __init__(self, tmp_path: Path) -> None:
        self.output = tmp_path / "out"
        self.project = tmp_path / "project"
        self.user_cwd = tmp_path / "user-cwd"
        self.home = tmp_path / "home"
        self.roots = {"home": self.home, "project": self.project, "user_cwd": self.user_cwd}
        for path in (self.output, self.project, self.user_cwd, self.home):
            path.mkdir(parents=True, exist_ok=True)
        self.calls: list[str] = []
        self.command_results: list[int] = [0]
        self.command_artifact_dirs: list[Path] = []
        self.seeded_sidecars: list[dict[str, object]] = []

    def completed(self, command, returncode: int) -> subprocess.CompletedProcess[str]:
        result = subprocess.CompletedProcess(list(command), returncode, "", "")
        result.started_at = "2026-06-02T00:00:00Z"
        result.duration_ms = 1
        return result

    def run_capture(self, command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        command_tuple = tuple(command)
        self.calls.append("command:" + " ".join(command_tuple))
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        returncode = self.command_results.pop(0) if self.command_results else 0
        return self.completed(command_tuple, returncode)

    def hooks(self, **overrides) -> scenario_lifecycle.ScenarioLifecycleHooks:
        def write_file_manifest(path, roots, **kwargs):
            self.calls.append(f"manifest:{Path(path).name}")
            Path(path).write_text("{}\n", encoding="utf-8")

        def scenario_file_state(scenario):
            self.calls.append(f"state:{scenario.platform}")
            return {f"{scenario.platform}/{scenario.scope}": {"exists": True}}

        def assert_expected_files(scenario):
            self.calls.append(f"expected:{scenario.platform}")
            return [{"ok": True, "detail": "expected"}]

        def assert_scope_boundaries(scenario):
            self.calls.append(f"scope:{scenario.platform}")
            return [{"ok": True, "detail": "scope"}]

        def unexpected_checks(scenario, *, phase):
            self.calls.append(f"unexpected:{phase}")
            return [{"ok": True, "detail": f"none_after_{phase}"}]

        def repeat_install_checks(scenario, before, after, *, phase):
            self.calls.append("idempotent")
            checks = [{"ok": True, "detail": "unchanged_after_repeat_install"}]
            checks.extend(unexpected_checks(scenario, phase=phase))
            return checks

        def seed_stale_sidecar_repair(scenario):
            self.calls.append(f"seed-stale:{scenario.platform}")
            return self.seeded_sidecars

        def stale_sidecar_repair_checks(scenario, *, phase):
            self.calls.append(f"sidecars:{scenario.platform}")
            checks = [{"ok": True, "detail": "sidecars"}]
            checks.extend(unexpected_checks(scenario, phase=phase))
            return checks

        def uninstall_checks(scenario, *, phase):
            self.calls.append(f"uninstalled:{scenario.platform}")
            checks = [{"ok": True, "detail": "removed"}]
            checks.extend(unexpected_checks(scenario, phase=phase))
            return checks

        def run_equivalence_check(scenario, env, artifact_dir):
            self.calls.append(f"equivalence:{scenario.platform}")
            return [{"ok": True, "detail": "equivalent"}]

        def command_artifact_summary(artifact_dir):
            path = Path(artifact_dir)
            self.command_artifact_dirs.append(path)
            return {"command": "graphify install", "transcript_path": "transcript.txt", "artifact_dir": str(path)}

        class FakeScenarioFileEffects:
            def seed_scenario_inputs(_, scenario):
                self.calls.append(f"seed:{scenario.platform}")

            def write_manifest(_, path, roots, **kwargs):
                write_file_manifest(path, roots, **kwargs)

            def capture_state(_, scenario):
                return scenario_file_state(scenario)

            def install_checks(_, scenario):
                return assert_expected_files(scenario) + assert_scope_boundaries(scenario)

            def unexpected_checks(_, scenario, *, phase):
                return unexpected_checks(scenario, phase=phase)

            def archive_generated_files(_, scenario, artifact_dir):
                self.calls.append(f"copy:{scenario.platform}")

            def repeat_install_checks(_, scenario, before, after, *, phase):
                return repeat_install_checks(scenario, before, after, phase=phase)

            def seed_stale_sidecar_repair(_, scenario):
                return seed_stale_sidecar_repair(scenario)

            def stale_sidecar_repair_checks(_, scenario, *, phase):
                return stale_sidecar_repair_checks(scenario, phase=phase)

            def uninstall_checks(_, scenario, *, phase):
                return uninstall_checks(scenario, phase=phase)

            def equivalence_checks(_, scenario, env, artifact_dir):
                return run_equivalence_check(scenario, env, artifact_dir)

            def universal_uninstall_checks(_, runner_scenario, installed_scenarios, install_checks):
                checks = list(install_checks)
                for scenario in installed_scenarios:
                    checks.extend(uninstall_checks(scenario, phase="universal_uninstall"))
                return checks

            def purge_checks(_, graphify_out, purged):
                return [{"path": str(graphify_out), "ok": purged, "detail": "purged" if purged else "still_exists"}]

        paths = overrides.pop(
            "paths",
            scenario_lifecycle.SandboxPaths(
                output=self.output,
                roots=self.roots,
                project=self.project,
                user_cwd=self.user_cwd,
                utc_timestamp=lambda: "2026-06-02T00:00:00Z",
                root_path=lambda root: self.roots[root],
                reset_sandbox_dirs=lambda: self.calls.append("reset"),
            ),
        )
        file_effects = overrides.pop(
            "file_effects",
            FakeScenarioFileEffects(),
        )
        commands = overrides.pop("commands", scenario_lifecycle.CommandExecutor(overrides.pop("run_capture", self.run_capture)))
        artifacts = overrides.pop(
            "artifacts",
            scenario_lifecycle.ScenarioArtifacts(
                risk_report=lambda scenario, passed: {"statuses": ["graphify_install_verified" if passed else "graphify_install_failed"]},
                command_artifact_summary=command_artifact_summary,
                combined_status=lambda passed: "graphify_install_verified" if passed else "graphify_install_failed",
                known_status_values=lambda: ["graphify_install_verified", "graphify_install_failed"],
            ),
        )
        matrix_overrides = overrides.pop(
            "matrix_overrides",
            scenario_lifecycle.MatrixRunnerOverrides(
                platform_scenarios=overrides.pop("platform_scenarios", None),
                run_scenario=overrides.pop("run_scenario_func", None),
                universal_uninstall_scenarios=overrides.pop("universal_uninstall_scenarios_func", None),
                run_universal_uninstall_scenario=overrides.pop("run_universal_uninstall_scenario_func", None),
                run_purge_scenario=overrides.pop("run_purge_scenario_func", None),
            ),
        )
        values = dict(paths=paths, file_effects=file_effects, commands=commands, artifacts=artifacts, matrix_overrides=matrix_overrides)
        values.update(overrides)
        return scenario_lifecycle.ScenarioLifecycleHooks(**values)


def assert_preserved_result_shape(result: dict[str, object]) -> None:
    assert PRESERVED_RESULT_FIELDS <= result.keys()
    assert isinstance(result["duration_ms"], int)
    assert isinstance(result["command_artifact"], dict)
    assert isinstance(result["reproduction_command"], str)


def artifact_names(path: Path) -> set[str]:
    return {item.name for item in path.iterdir() if item.is_file()}


def test_file_effects_interface_omits_oracle_leaf_helpers() -> None:
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
    assert result["command_artifact"]["artifact_dir"] == str(factory.output / "scenarios" / "codex-project")
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


def test_universal_uninstall_scenario_writes_assertions_and_risk_artifacts(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    scenarios = [make_scenario("first", "project"), make_scenario("second", "project")]

    result = scenario_lifecycle.run_universal_uninstall_scenario("project", scenarios, {}, hooks=hooks)
    artifact_dir = factory.output / "scenarios" / "universal-uninstall-project"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["id"] == "universal-uninstall-project"
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert result["command_artifact"]["artifact_dir"] == str(artifact_dir / "uninstall")
    assert factory.command_artifact_dirs == [artifact_dir / "uninstall"]
    assert "target_runtime_verification" not in result
    assert assertions["uninstall_command"] == ["graphify", "uninstall", "--project"]
    assert assertions["uninstall_exit_code"] == 0
    assert [item["scenario_id"] for item in assertions["install_results"]] == ["first-project", "second-project"]
    assert risks["statuses"] == ["graphify_install_verified"]
    assert "target_runtime_verification" not in result


def test_purge_scenario_removes_disposable_graphify_out_and_writes_artifacts(tmp_path) -> None:
    factory = HookFactory(tmp_path)

    def purge_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        graphify_out = factory.project / "graphify-out"
        if graphify_out.exists():
            for child in graphify_out.iterdir():
                child.unlink()
            graphify_out.rmdir()
        return factory.completed(command, 0)

    result = scenario_lifecycle.run_purge_scenario({}, hooks=factory.hooks(run_capture=purge_run_capture))
    purge_scenario_id = DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id()
    artifact_dir = factory.output / "scenarios" / purge_scenario_id
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert_preserved_result_shape(result)
    assert result["id"] == purge_scenario_id
    assert result["graphify_file_effects_passed"] is True
    assert result["overall_status"] == "graphify_install_verified"
    assert result["command_artifact"]["artifact_dir"] == str(artifact_dir / "uninstall-purge")
    assert factory.command_artifact_dirs == [artifact_dir / "uninstall-purge"]
    assert "target_runtime_verification" not in result
    assert assertions["uninstall_exit_code"] == 0
    assert assertions["checks"] == [{"path": str(factory.project / "graphify-out"), "ok": True, "detail": "purged"}]
    assert risks["statuses"] == ["graphify_install_verified"]
    assert not (factory.project / "graphify-out").exists()


def test_matrix_collects_graphify_failures(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []

    def platform_scenarios(platform_name: str, scope: str):
        return [make_scenario(platform_name, "project", uninstall=False)]

    def run_scenario(item, env):
        calls.append(item.platform)
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": False, "graphify_file_effects_passed": False}

    def unexpected_universal(*args, **kwargs):
        raise AssertionError("universal uninstall should not run after a Graphify install failure")

    def unexpected_purge(*args, **kwargs):
        raise AssertionError("purge scenario should not run after a Graphify install failure")

    hooks = factory.hooks(
        platform_scenarios=platform_scenarios,
        run_scenario_func=run_scenario,
        universal_uninstall_scenarios_func=unexpected_universal,
        run_purge_scenario_func=unexpected_purge,
    )

    results = scenario_lifecycle.run_matrix_scenarios(["first", "second"], "project", {}, hooks=hooks)

    assert calls == ["first", "second"]
    assert len(results) == 2
    assert all(result["passed"] is False for result in results)


def test_matrix_skips_universal_uninstall_and_purge_until_all_standard_scenarios_pass(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []

    def platform_scenarios(platform_name: str, scope: str):
        return [make_scenario(platform_name, "project", uninstall=False)]

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {
            "id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope),
            "platform": item.platform,
            "scope": item.scope,
            "passed": item.platform == "second",
            "graphify_file_effects_passed": item.platform == "second",
        }

    def unexpected_universal(*args, **kwargs):
        raise AssertionError("universal uninstall should run only after all standard scenarios pass")

    def unexpected_purge(*args, **kwargs):
        raise AssertionError("purge should run only after all standard scenarios pass")

    results = scenario_lifecycle.run_matrix_scenarios(
        ["first", "second"],
        "project",
        {},
        hooks=factory.hooks(
            platform_scenarios=platform_scenarios,
            run_scenario_func=run_scenario,
            universal_uninstall_scenarios_func=unexpected_universal,
            run_purge_scenario_func=unexpected_purge,
        ),
    )

    assert calls == ["scenario:first", "scenario:second"]
    assert [result["passed"] for result in results] == [False, True]


def test_matrix_fail_fast_stops_first_graphify_failure(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []

    def platform_scenarios(platform_name: str, scope: str):
        return [make_scenario(platform_name, "project", uninstall=False)]

    def run_scenario(item, env):
        calls.append(item.platform)
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": False}

    results = scenario_lifecycle.run_matrix_scenarios(
        ["first", "second"],
        "project",
        {},
        hooks=factory.hooks(platform_scenarios=platform_scenarios, run_scenario_func=run_scenario),
        fail_fast_scenarios=True,
    )

    assert calls == ["first"]
    assert len(results) == 1
    assert results[0]["passed"] is False


def test_matrix_collects_universal_failures_and_runs_purge(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []

    def platform_scenarios(platform_name: str, scope: str):
        return [make_scenario(platform_name, "project", uninstall=False)]

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": True}

    def universal_groups(platforms, scope):
        return [("user", [make_scenario("first", "user"), make_scenario("second", "user")]), ("project", [make_scenario("first", "project"), make_scenario("second", "project")])]

    def run_universal(universal_scope, scenarios, env):
        calls.append(f"universal:{universal_scope}")
        return {"id": DEFAULT_SCENARIO_REGISTRY.universal_uninstall_scenario_id(universal_scope), "platform": "multiple", "scope": universal_scope, "passed": False}

    def run_purge(env):
        calls.append("purge")
        return {"id": DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id(), "platform": "purge", "scope": "project", "passed": False}

    results = scenario_lifecycle.run_matrix_scenarios(
        ["first", "second"],
        "both",
        {},
        hooks=factory.hooks(
            platform_scenarios=platform_scenarios,
            run_scenario_func=run_scenario,
            universal_uninstall_scenarios_func=universal_groups,
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


def test_matrix_runs_purge_for_project_scope_after_standard_scenarios_pass(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    calls: list[str] = []

    def platform_scenarios(platform_name: str, scope: str):
        return [make_scenario(platform_name, "project", uninstall=False)]

    def run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {"id": DEFAULT_SCENARIO_REGISTRY.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": True}

    def universal_groups(platforms, scope):
        calls.append(f"universal-groups:{scope}")
        return []

    def run_purge(env):
        calls.append("purge")
        return {"id": DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id(), "platform": "purge", "scope": "project", "passed": True}

    results = scenario_lifecycle.run_matrix_scenarios(
        ["first", "second"],
        "project",
        {},
        hooks=factory.hooks(
            platform_scenarios=platform_scenarios,
            run_scenario_func=run_scenario,
            universal_uninstall_scenarios_func=universal_groups,
            run_purge_scenario_func=run_purge,
        ),
    )

    assert calls == ["scenario:first", "scenario:second", "universal-groups:project", "purge"]
    assert results[-1]["id"] == DEFAULT_SCENARIO_REGISTRY.purge_disposable_graphify_out_scenario_id()
