from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from tools.install_sandbox import command_runner, reports, sandbox_runner, scenario_lifecycle_plan, source_snapshot, status
from tools.install_sandbox.platform_specs import ExpectedPath, Scenario


def test_parse_args_requires_platform_or_all() -> None:
    args = sandbox_runner.parse_args(["--platform", "codex", "--scope", "project", "--copy-source", "auto", "--fail-fast-scenarios"])

    assert args.platform == "codex"
    assert args.all is False
    assert args.scope == "project"
    assert args.copy_source == "auto"
    assert args.fail_fast_scenarios is True


def test_dockerfile_copies_direct_runner_imports() -> None:
    dockerfile = Path("tools/install_sandbox/Dockerfile").read_text(encoding="utf-8")

    for module in (
        "agent_summary.py",
        "expected_effects.py",
        "file_effect_generated_artifacts.py",
        "file_effect_oracle.py",
        "file_effect_sidecars.py",
        "file_effect_state.py",
        "file_effect_surfaces.py",
        "file_walk.py",
        "harness_specs.py",
        "install_surface_core.py",
        "install_surface_generated.py",
        "install_surface_sidecars.py",
        "install_surface_state.py",
        "install_surface_statuses.py",
        "json_helpers.py",
        "platform_specs.py",
        "scenario_file_effects_adapter.py",
        "scenario_lifecycle_disposable.py",
        "scenario_lifecycle_plan.py",
        "scenario_lifecycle_support.py",
        "scenario_lifecycle_standard.py",
        "scenario_lifecycle_universal.py",
        "spec_loader.py",
        "status.py",
        "validation_plan.py",
    ):
        assert f"COPY {module} /runner/{module}" in dockerfile
    for future_platform_specs_owner in (
        "install_target_models.py",
        "install_target_catalog.py",
        "install_target_defaults.py",
    ):
        if Path("tools/install_sandbox", future_platform_specs_owner).exists():
            assert f"COPY {future_platform_specs_owner} /runner/{future_platform_specs_owner}" in dockerfile
    assert "COPY file_effects.py /runner/file_effects.py" not in dockerfile
    assert "COPY specs /runner/specs" in dockerfile


def test_sandbox_runner_imports_file_effect_owner_modules() -> None:
    tree = ast.parse(Path(sandbox_runner.__file__).read_text(encoding="utf-8"))
    module_imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_imports.update(alias.name for alias in node.names)

    assert "file_effects" not in module_imports
    assert "scenario_lifecycle" not in module_imports
    assert {
        "file_effect_generated_artifacts",
        "file_effect_oracle",
        "file_effect_state",
        "scenario_file_effects_adapter",
        "scenario_lifecycle_plan",
        "scenario_lifecycle_support",
    } <= module_imports


def test_sandbox_env_uses_isolated_home_xdg_project_and_path(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    xdg = home / ".config"
    project = tmp_path / "project"
    monkeypatch.setattr(sandbox_runner, "HOME", home)
    monkeypatch.setattr(sandbox_runner, "XDG_CONFIG_HOME", xdg)
    monkeypatch.setattr(sandbox_runner, "PROJECT", project)
    monkeypatch.setenv("PATH", "/usr/bin")

    env = sandbox_runner.sandbox_env()

    assert env["HOME"] == str(home)
    assert env["XDG_CONFIG_HOME"] == str(xdg)
    assert env["GRAPHIFY_PROJECT"] == str(project)
    assert env["PATH"].startswith(str(home / ".local" / "bin"))
    assert env["PATH"].endswith(":/usr/bin")


def test_main_records_tier1_runtime_boundary_and_writes_artifacts(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    calls: list[str] = []

    scenario = Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install", "--project", "--platform", "codex"),
        uninstall_command=None,
        cwd_root="project",
        expected=(ExpectedPath("project", "AGENTS.md"),),
    )

    monkeypatch.setattr(sandbox_runner, "OUTPUT", output)
    monkeypatch.setattr(sandbox_runner, "sandbox_env", lambda: calls.append("env") or {"HOME": "/tmp/graphify-home"})
    def preflight() -> dict[str, object]:
        calls.append("preflight")
        output.mkdir(parents=True, exist_ok=True)
        return {"project": "/tmp/graphify-project"}

    monkeypatch.setattr(sandbox_runner, "preflight", preflight)
    monkeypatch.setattr(source_snapshot, "copy_source_tree", lambda copy_source="always", *, config: calls.append(f"copy:{copy_source}") or {"root": "/tmp/graphify-src", "copy_source_mode": copy_source})
    monkeypatch.setattr(sandbox_runner, "install_graphify", lambda env: calls.append("install-package") or {"version": "test", "install_mode": "normal"})

    class Registry:
        specs = {"codex": object()}

        def platform_scenarios(self, platform_name: str, scope: str):
            return [scenario]

    monkeypatch.setattr(sandbox_runner, "SCENARIO_REGISTRY", Registry())
    class Plan:
        platforms = ("codex",)
        requested_scope = "project"
        standard_scenarios = (scenario,)
        universal_uninstall = ()
        disposable_artifacts = ()
        coverage_records = (
            {
                "platform": "codex",
                "scope": "project",
                "status": "runnable",
                "scenario_id": "codex-project",
                "install_command": list(scenario.install_command),
                "uninstall_command": None,
                "generic_direct_equivalence": {"status": "not_applicable"},
                "risk_notes": [],
            },
        )
        target_runtime_validation_sections = ({"section_title": "Synthetic Runtime", "status": "declared"},)
        platform_coverage_summary = {
            "registered_platform_count": 99,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 77,
        }
        target_runtime_verification = {
            "performed": False,
            "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
        }

        platform_coverage = ({"platform": "legacy-alias", "status": "must-not-appear"},)
        runtime_limitation_sections = ({"section_title": "Legacy Alias", "status": "must-not-appear"},)

    plan = Plan()
    def build_plan(registry, *, all_platforms, platform_name=None, scope="both", **kwargs):
        assert registry is sandbox_runner.SCENARIO_REGISTRY
        calls.append(f"plan:{platform_name}:{scope}:{all_platforms}")
        return plan

    monkeypatch.setattr(
        sandbox_runner.validation_plan,
        "build_validation_plan",
        build_plan,
    )
    monkeypatch.setattr(
        scenario_lifecycle_plan,
        "run_validation_plan",
        lambda plan_arg, env, hooks, fail_fast_scenarios=False: calls.append(f"validation-plan:{plan_arg.requested_scope}:{fail_fast_scenarios}")
        or [
            {
                "id": "codex-project",
                "platform": "codex",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
            }
        ],
    )
    monkeypatch.setattr(sandbox_runner, "read_os_release", lambda: {"PRETTY_NAME": "Synthetic Linux"})
    monkeypatch.setattr(reports, "write_report_md", lambda path, manifest: Path(path).write_text("report\n", encoding="utf-8"))

    exit_code = sandbox_runner.main(["--platform", "codex", "--scope", "project", "--copy-source", "auto", "--fail-fast-scenarios"])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert calls == ["env", "preflight", "copy:auto", "install-package", "plan:codex:project:False", "validation-plan:project:True"]
    assert (output / "report.md").read_text(encoding="utf-8") == "report\n"
    assert (output / "agent-summary.md").exists()
    assert json.loads((output / "agent-summary.json").read_text(encoding="utf-8"))["status"] == "FAIL"
    assert manifest["target_runtime_verification"] == {
        "performed": False,
        "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
    }
    assert manifest["target_runtime_validation_sections"] == [{"section_title": "Synthetic Runtime", "status": "declared"}]
    assert "target_tool_runtime" not in manifest
    assert manifest["platform_coverage"] == list(plan.coverage_records)
    assert "legacy-alias" not in json.dumps(manifest)
    assert "Legacy Alias" not in json.dumps(manifest)
    assert manifest["scenario_count"] == len(manifest["results"])
    assert manifest["graphify_file_effect_fail_count"] == 1
    assert manifest["platform_coverage_summary"]["runnable_scope_count"] == 1
    assert manifest["platform_coverage_summary"]["registered_platform_count"] == 99
    assert manifest["platform_coverage_summary"]["unsupported_scope_count"] == 77
    assert manifest["platform_coverage_summary"]["universal_scenario_count"] == 0


def test_main_manifest_counts_executed_synthetic_validations(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"

    scenario = Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install", "--project", "--platform", "codex"),
        uninstall_command=None,
        cwd_root="project",
        expected=(ExpectedPath("project", "AGENTS.md"),),
    )

    monkeypatch.setattr(sandbox_runner, "OUTPUT", output)
    monkeypatch.setattr(sandbox_runner, "sandbox_env", lambda: {"HOME": "/tmp/graphify-home"})

    def preflight() -> dict[str, object]:
        output.mkdir(parents=True, exist_ok=True)
        return {"project": "/tmp/graphify-project"}

    monkeypatch.setattr(sandbox_runner, "preflight", preflight)
    monkeypatch.setattr(
        source_snapshot,
        "copy_source_tree",
        lambda copy_source="always", *, config: {"root": "/tmp/graphify-src", "copy_source_mode": copy_source},
    )
    monkeypatch.setattr(sandbox_runner, "install_graphify", lambda env: {"version": "test", "install_mode": "normal"})

    class Plan:
        platforms = ("codex",)
        requested_scope = "project"
        standard_scenarios = (scenario,)
        coverage_records = (
            {
                "platform": "codex",
                "scope": "project",
                "status": "runnable",
                "scenario_id": "codex-project",
                "install_command": list(scenario.install_command),
            },
        )
        target_runtime_validation_sections = ()
        platform_coverage_summary = {
            "registered_platform_count": 1,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 0,
        }
        target_runtime_verification = {"performed": False}

    plan = Plan()
    monkeypatch.setattr(sandbox_runner.validation_plan, "build_validation_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        scenario_lifecycle_plan,
        "run_validation_plan",
        lambda *args, **kwargs: [
            {
                "id": "codex-project",
                "platform": "codex",
                "scope": "project",
                "passed": True,
                "graphify_file_effects_passed": True,
            },
            {
                "id": "universal-cleanup",
                "platform": "universal",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
            },
        ],
    )
    monkeypatch.setattr(sandbox_runner, "read_os_release", lambda: {"PRETTY_NAME": "Synthetic Linux"})
    monkeypatch.setattr(reports, "write_report_md", lambda path, manifest: Path(path).write_text("report\n", encoding="utf-8"))

    exit_code = sandbox_runner.main(["--platform", "codex", "--scope", "project"])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert manifest["scenario_count"] == 2
    assert manifest["graphify_file_effect_pass_count"] == 1
    assert manifest["graphify_file_effect_fail_count"] == 1
    assert manifest["pass_count"] == 1
    assert manifest["fail_count"] == 1
    assert manifest["platform_coverage_summary"]["universal_scenario_count"] == 1


def test_install_graphify_version_probe_failure_is_precondition(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    source = tmp_path / "graphify-src"
    calls: list[str] = []
    monkeypatch.setattr(sandbox_runner, "OUTPUT", output)
    monkeypatch.setattr(sandbox_runner, "SRC", source)
    monkeypatch.setattr(source_snapshot, "read_installed_package_metadata", lambda package_name, source_path, *, home=None: {"installed_from_copied_source": True})

    def run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        calls.append(command_class)
        if command_class == "package_install":
            return subprocess.CompletedProcess(list(command), 0, "installed", "")
        return subprocess.CompletedProcess(list(command), 1, "", "missing graphify")

    monkeypatch.setattr(command_runner, "run_capture", run_capture)

    with pytest.raises(RuntimeError, match="graphify version probe failed"):
        sandbox_runner.install_graphify({})

    assert calls == ["package_install", "graphify_version"]


def test_install_graphify_rejects_wrong_package_provenance_after_probe(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    source = tmp_path / "graphify-src"
    monkeypatch.setattr(sandbox_runner, "OUTPUT", output)
    monkeypatch.setattr(sandbox_runner, "SRC", source)
    monkeypatch.setattr(
        source_snapshot,
        "read_installed_package_metadata",
        lambda package_name, source_path, *, home=None: {
            "package_name": "graphifyy",
            "location": "/tmp/site-packages",
            "direct_url": {"url": "file:///tmp/not-graphify-src"},
            "installed_from_copied_source": False,
        },
    )

    def run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        if command_class == "package_install":
            return subprocess.CompletedProcess(list(command), 0, "installed", "")
        return subprocess.CompletedProcess(list(command), 0, "graphify 9.9.9", "")

    monkeypatch.setattr(command_runner, "run_capture", run_capture)

    with pytest.raises(RuntimeError) as excinfo:
        sandbox_runner.install_graphify({})

    message = str(excinfo.value)
    assert "provenance check failed" in message
    assert "direct_url=" in message
    assert "expected_source=" in message


def test_runner_status_helpers_are_file_effect_only() -> None:
    scenario = Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install", "--platform", "codex"),
        uninstall_command=None,
        cwd_root="project",
        expected=(ExpectedPath("project", "AGENTS.md"),),
    )

    report = sandbox_runner.risk_report(scenario, True)

    assert sandbox_runner.combined_status(True) == sandbox_runner.RISK_GRAPHIFY_VERIFIED
    assert sandbox_runner.combined_status(False) == sandbox_runner.RISK_GRAPHIFY_FAILED
    assert sandbox_runner.RISK_GRAPHIFY_VERIFIED == status.RISK_GRAPHIFY_VERIFIED == "graphify_install_verified"
    assert sandbox_runner.RISK_GRAPHIFY_FAILED == status.RISK_GRAPHIFY_FAILED == "graphify_install_failed"
    assert sandbox_runner.known_status_values() == reports.known_status_values() == status.known_status_values()
    assert report["statuses"] == [sandbox_runner.RISK_GRAPHIFY_VERIFIED]
    assert "target_tool_runtime_verified" not in report
