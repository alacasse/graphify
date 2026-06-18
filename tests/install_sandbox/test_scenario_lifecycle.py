from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

from tools.install_sandbox import scenario_lifecycle, validation_plan
from tools.install_sandbox.platform_specs import (
    DEFAULT_SCENARIO_REGISTRY,
    DisposableArtifactScenarioSpec,
    DisposableSeedFile,
    InstallSurface,
    Scenario,
    SelectedUniversalUninstallScenario,
    UniversalUninstallScenarioSpec,
)


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


# Lifecycle tests depend on the ScenarioFileEffects protocol. Direct Installer
# Core decisions live in test_install_surface_core*.py topic modules; the
# concrete adapter boundary lives in test_file_effects.py.


def make_scenario(platform: str = "codex", scope: str = "project", *, uninstall: bool = True) -> Scenario:
    return Scenario(
        platform=platform,
        scope=scope,
        install_command=("graphify", "install", "--platform", platform),
        uninstall_command=("graphify", "uninstall", "--platform", platform) if uninstall else None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=(InstallSurface("project" if scope == "project" else "home", f"{platform}-{scope}.md"),),
    )


def make_validation_plan(
    *,
    platforms: tuple[str, ...] = ("codex",),
    scope: str = "project",
    standard_scenarios: tuple[Scenario, ...] = (),
    universal_uninstall: tuple[scenario_lifecycle.SelectedUniversalUninstallScenario, ...] = (),
    disposable_artifacts: tuple[DisposableArtifactScenarioSpec, ...] = (),
) -> validation_plan.ValidationPlan:
    coverage_records = tuple(
        {
            "platform": scenario.platform,
            "scope": scenario.scope,
            "status": "runnable",
            "scenario_id": DEFAULT_SCENARIO_REGISTRY.scenario_id(scenario.platform, scenario.scope),
            "install_command": list(scenario.install_command),
            "uninstall_command": None if scenario.uninstall_command is None else list(scenario.uninstall_command),
            "generic_direct_equivalence": {"status": "not_applicable"},
            "risk_notes": [],
        }
        for scenario in standard_scenarios
    )
    return validation_plan.ValidationPlan(
        platforms=platforms,
        requested_scope=scope,
        standard_scenarios=standard_scenarios,
        universal_uninstall=universal_uninstall,
        disposable_artifacts=disposable_artifacts,
        coverage_records=coverage_records,
        target_runtime_validation_sections=(),
        platform_coverage_summary={
            "registered_platform_count": len(platforms),
            "requested_scope": scope,
            "runnable_scope_count": len(standard_scenarios),
            "universal_scenario_count": len(universal_uninstall) + len(disposable_artifacts),
            "unsupported_scope_count": 0,
        },
    )


def make_universal_uninstall_selection(
    scenarios: tuple[Scenario, ...],
    *,
    scenario_id: str = "universal-uninstall-project",
    platform_label: str = "multiple",
    scope: str = "project",
    command: tuple[str, ...] = ("graphify", "uninstall", "--project"),
    cwd_root: str = "project",
    eligible_platform_scope: str = "project",
    artifact_subdir: str = "uninstall",
    risk_note: str = "universal uninstall covers Graphify-owned file effects after multiple installs",
) -> SelectedUniversalUninstallScenario:
    return SelectedUniversalUninstallScenario(
        UniversalUninstallScenarioSpec(
            scenario_id=scenario_id,
            platform_label=platform_label,
            scope=scope,
            command=command,
            cwd_root=cwd_root,
            eligible_platform_scope=eligible_platform_scope,
            artifact_subdir=artifact_subdir,
            risk_note=risk_note,
        ),
        scenarios,
    )


def make_disposable_graphify_out_spec() -> DisposableArtifactScenarioSpec:
    return DisposableArtifactScenarioSpec(
        scenario_id="purge-disposable-graphify-out",
        platform_label="purge",
        scope="project",
        command=("graphify", "uninstall", "--purge"),
        cwd_root="project",
        artifact_subdir="uninstall-purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(DisposableSeedFile("graph.json", '{"nodes": [], "edges": []}\n'),),
        scope_eligibility=("project", "both"),
        risk_note="purge verified only against disposable sandbox graphify-out state",
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
        self.captured_artifact_dirs: list[Path] = []
        self.command_records: list[dict[str, object]] = []
        self.manifest_records: list[dict[str, object]] = []
        self.seeded_sidecars: list[dict[str, object]] = []
        self.universal_check_ok = True
        self.disposable_check_records: list[dict[str, object]] = []

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
            self.captured_artifact_dirs.append(Path(artifact_dir))
        self.command_records.append(
            {
                "command": command_tuple,
                "cwd": Path(cwd),
                "artifact_dir": None if artifact_dir is None else Path(artifact_dir),
                "command_class": command_class,
                "timeout_seconds": timeout_seconds,
            }
        )
        returncode = self.command_results.pop(0) if self.command_results else 0
        return self.completed(command_tuple, returncode)

    def hooks(self, **overrides) -> scenario_lifecycle.ScenarioLifecycleHooks:
        def write_file_manifest(path, roots, **kwargs):
            self.calls.append(f"manifest:{Path(path).name}")
            self.manifest_records.append({"filename": Path(path).name, "path": Path(path), "kwargs": dict(kwargs)})
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

        class ScenarioFileEffectsDouble:
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
                if not self.universal_check_ok:
                    checks.append({"ok": False, "detail": "universal_uninstall_failed"})
                return checks

            def disposable_artifact_checks(_, disposable_path, removed):
                path = Path(disposable_path)
                self.calls.append(f"disposable-check:{path.name}")
                check = {"path": str(path), "ok": removed, "detail": "purged" if removed else "still_exists"}
                self.disposable_check_records.append(check)
                return [check]

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
            ScenarioFileEffectsDouble(),
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
                run_scenario=overrides.pop("run_scenario_func", None),
                run_universal_uninstall_scenario=overrides.pop("run_universal_uninstall_scenario_func", None),
                run_purge_scenario=overrides.pop("run_purge_scenario_func", None),
                run_disposable_artifact_scenario=overrides.pop("run_disposable_artifact_scenario_func", None),
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


def command_artifact_dir(result: dict[str, object]) -> str:
    return str(cast(dict[str, object], result["command_artifact"])["artifact_dir"])


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


def test_universal_uninstall_scenario_writes_assertions_and_risk_artifacts(tmp_path) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    scenarios = (make_scenario("first", "project"), make_scenario("second", "project"))
    selected = make_universal_uninstall_selection(scenarios)

    result = scenario_lifecycle.run_universal_uninstall_scenario(selected, env={}, hooks=hooks)
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
        "uninstalled:first",
        "unexpected:universal_uninstall",
        "uninstalled:second",
        "unexpected:universal_uninstall",
        "manifest:after-uninstall-files.json",
    ]


def test_universal_uninstall_scenario_derives_failure_from_installs_uninstall_and_checks(tmp_path) -> None:
    scenarios = (make_scenario("first", "project"), make_scenario("second", "project"))
    selected = make_universal_uninstall_selection(scenarios)

    factory = HookFactory(tmp_path / "install-fails")
    factory.command_results = [1, 0, 0]
    result = scenario_lifecycle.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "universal-uninstall-project" / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert [item["exit_code"] for item in assertions["install_results"]] == [1, 0]

    factory = HookFactory(tmp_path / "uninstall-fails")
    factory.command_results = [0, 0, 1]
    result = scenario_lifecycle.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
    assertions = json.loads((factory.output / "scenarios" / "universal-uninstall-project" / "assertions.json").read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert assertions["passed"] is False
    assert assertions["uninstall_exit_code"] == 1

    factory = HookFactory(tmp_path / "checks-fail")
    factory.command_results = [0, 0, 0]
    factory.universal_check_ok = False
    result = scenario_lifecycle.run_universal_uninstall_scenario(selected, env={}, hooks=factory.hooks())
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
        eligible_platform_scope="unused-scope",
        artifact_subdir="declared-artifacts",
        risk_note="declared lifecycle risk",
    )

    result = scenario_lifecycle.run_universal_uninstall_scenario(
        selected,
        env={},
        hooks=factory.hooks(),
    )
    artifact_dir = factory.output / "scenarios" / "sweep-custom-workspace"
    assertions = json.loads((artifact_dir / "assertions.json").read_text(encoding="utf-8"))
    risks = json.loads((artifact_dir / "risk.json").read_text(encoding="utf-8"))

    assert result["id"] == "sweep-custom-workspace"
    assert result["platform"] == "synthetic-cleaner"
    assert result["scope"] == "workspace"
    assert command_artifact_dir(result) == str(artifact_dir / "declared-artifacts")
    assert assertions["uninstall_command"] == ["custom-tool", "remove", "workspace"]
    assert factory.command_records[-1]["command"] == ("custom-tool", "remove", "workspace")
    assert factory.command_records[-1]["cwd"] == factory.user_cwd
    assert risks["notes"] == ["declared lifecycle risk"]


def test_run_universal_uninstall_scenario_preserves_legacy_scope_wrapper(tmp_path, monkeypatch) -> None:
    factory = HookFactory(tmp_path)
    hooks = factory.hooks()
    env = {"HOME": str(factory.home)}
    scenarios = [make_scenario("alpha", "project"), make_scenario("beta", "project")]
    spec = UniversalUninstallScenarioSpec(
        scenario_id="legacy-workspace-sweep",
        platform_label="legacy-cleaner",
        scope="workspace",
        command=("cleanup", "workspace"),
        cwd_root="project",
        eligible_platform_scope="project",
    )
    calls: list[tuple[str, object]] = []

    def select_spec(scope, *, hooks):
        calls.append(("select", scope, hooks))
        return spec

    class FakeUniversalUninstallLifecycle:
        def __init__(self, spec_arg, scenarios_arg, env_arg, hooks_arg) -> None:
            calls.append(("lifecycle", spec_arg, scenarios_arg, env_arg, hooks_arg))

        def run(self):
            calls.append(("run",))
            return {"id": spec.scenario_id, "passed": True}

    monkeypatch.setattr(scenario_lifecycle, "universal_uninstall_spec_for_scope", select_spec)
    monkeypatch.setattr(scenario_lifecycle, "UniversalUninstallLifecycle", FakeUniversalUninstallLifecycle)

    result = scenario_lifecycle.run_universal_uninstall_scenario("workspace", scenarios, env, hooks=hooks)

    assert result == {"id": "legacy-workspace-sweep", "passed": True}
    assert calls == [
        ("select", "workspace", hooks),
        ("lifecycle", spec, scenarios, env, hooks),
        ("run",),
    ]


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
