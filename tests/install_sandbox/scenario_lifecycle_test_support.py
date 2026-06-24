from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from tools.install_sandbox import validation_plan
from tools.install_sandbox.lifecycle import scenario_lifecycle_support
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
    universal_uninstall: tuple[SelectedUniversalUninstallScenario, ...] = (),
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

    def hooks(self, **overrides) -> scenario_lifecycle_support.ScenarioLifecycleHooks:
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
            scenario_lifecycle_support.SandboxPaths(
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
        commands = overrides.pop("commands", scenario_lifecycle_support.CommandExecutor(overrides.pop("run_capture", self.run_capture)))
        artifacts = overrides.pop(
            "artifacts",
            scenario_lifecycle_support.ScenarioArtifacts(
                risk_report=lambda scenario, passed: {"statuses": ["graphify_install_verified" if passed else "graphify_install_failed"]},
                command_artifact_summary=command_artifact_summary,
                combined_status=lambda passed: "graphify_install_verified" if passed else "graphify_install_failed",
                known_status_values=lambda: ["graphify_install_verified", "graphify_install_failed"],
            ),
        )
        matrix_overrides = overrides.pop(
            "matrix_overrides",
            scenario_lifecycle_support.MatrixRunnerOverrides(
                run_scenario=overrides.pop("run_scenario_func", None),
                run_universal_uninstall_scenario=overrides.pop("run_universal_uninstall_scenario_func", None),
                run_purge_scenario=overrides.pop("run_purge_scenario_func", None),
                run_disposable_artifact_scenario=overrides.pop("run_disposable_artifact_scenario_func", None),
            ),
        )
        values = dict(paths=paths, file_effects=file_effects, commands=commands, artifacts=artifacts, matrix_overrides=matrix_overrides)
        values.update(overrides)
        return scenario_lifecycle_support.ScenarioLifecycleHooks(**values)


def assert_preserved_result_shape(result: dict[str, object]) -> None:
    assert PRESERVED_RESULT_FIELDS <= result.keys()
    assert isinstance(result["duration_ms"], int)
    assert isinstance(result["command_artifact"], dict)
    assert isinstance(result["reproduction_command"], str)


def artifact_names(path: Path) -> set[str]:
    return {item.name for item in path.iterdir() if item.is_file()}


def command_artifact_dir(result: dict[str, object]) -> str:
    return str(cast(dict[str, object], result["command_artifact"])["artifact_dir"])
