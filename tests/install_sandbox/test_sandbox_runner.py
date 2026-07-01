from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox import sandbox_runner
from tools.install_sandbox.harness_specs import SandboxRootRegistry, SandboxRootSpec
from tools.install_sandbox.reporting import harness_run
from tools.install_sandbox.reporting import status as reporting_status
from tools.install_sandbox.lifecycle import scenario_lifecycle_plan
from tools.install_sandbox.reporting import reports
from tools.install_sandbox.runtime import harness_orchestration
from tools.install_sandbox.runtime import command_runner, sandbox_run_environment, source_snapshot
from tools.install_sandbox.runtime.sandbox_run_environment import SandboxRunEnvironment
from tools.install_sandbox.surfaces.install_surface_models import ExpectedPath
from tools.install_sandbox.targets.install_target_models import (
    DisposableArtifactScenarioSpec,
    InstallTargetSpec,
    Scenario,
    ScopeSpec,
    UniversalUninstallScenarioSpec,
)


def test_parse_args_requires_platform_or_all() -> None:
    args = sandbox_runner.parse_args(["--platform", "codex", "--scope", "project", "--copy-source", "auto", "--fail-fast-scenarios"])

    assert args.platform == "codex"
    assert args.all is False
    assert args.scope == "project"
    assert args.copy_source == "auto"
    assert args.fail_fast_scenarios is True


def test_parse_args_keeps_public_cli_contract_explicit() -> None:
    all_args = sandbox_runner.parse_args(["--all"])

    assert all_args.all is True
    assert all_args.platform is None
    assert all_args.scope == "both"
    assert all_args.copy_source == "always"
    assert all_args.fail_fast_scenarios is False

    with pytest.raises(SystemExit):
        sandbox_runner.parse_args([])
    with pytest.raises(SystemExit):
        sandbox_runner.parse_args(["--platform", "codex", "--all"])
    with pytest.raises(SystemExit):
        sandbox_runner.parse_args(["--platform", "codex", "--scope", "workspace"])
    with pytest.raises(SystemExit):
        sandbox_runner.parse_args(["--platform", "codex", "--copy-source", "never"])


def test_dockerfile_uses_package_layout() -> None:
    dockerfile = Path("tools/install_sandbox/Dockerfile").read_text(encoding="utf-8")
    dockerignore = Path("tools/install_sandbox/.dockerignore").read_text(encoding="utf-8").splitlines()

    assert "PYTHONPATH=/runner" in dockerfile
    assert "touch /runner/tools/__init__.py" in dockerfile
    assert "COPY . /runner/tools/install_sandbox/" in dockerfile
    assert dockerfile.count("COPY ") == 1
    assert 'ENTRYPOINT ["python", "-m", "tools.install_sandbox.sandbox_runner"]' in dockerfile
    assert not re.search(r"(?m)^COPY\s+\S+\.py\s+/runner/\S+\.py\b", dockerfile)
    assert "COPY specs /runner/specs" not in dockerfile
    assert {"out/", "__pycache__/", "*.pyc", ".pytest_cache/"}.issubset(set(dockerignore))


def test_sandbox_runner_compatibility_imports_stay_on_owner_modules() -> None:
    tree = ast.parse(Path(sandbox_runner.__file__).read_text(encoding="utf-8"))
    module_imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                module_imports.add(node.module)
            module_imports.update(alias.name for alias in node.names)

    assert "file_effects" not in module_imports
    assert "scenario_lifecycle" not in module_imports
    assert "platform_specs" not in module_imports
    assert "SandboxRunEnvironment" in module_imports
    assert "file_effect_oracle" not in module_imports
    assert "scenario_file_effects_adapter" not in module_imports
    assert "agent_summary" not in module_imports
    assert "reports" not in module_imports
    assert "harness_orchestration" in module_imports


def test_sandbox_runner_adapter_boundary_does_not_regrow_orchestration() -> None:
    tree = ast.parse(Path(sandbox_runner.__file__).read_text(encoding="utf-8"))
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_names.add(node.module.rsplit(".", 1)[-1])
            imported_names.update(alias.name for alias in node.names)

    assert {
        "scenario_lifecycle_plan",
        "reports",
        "agent_summary",
        "command_runner",
        "source_snapshot",
        "container_runtime",
    }.isdisjoint(imported_names)

    main_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    called_attributes = {
        node.attr
        for node in ast.walk(main_node)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }

    assert "run_harness_and_write_outputs" not in called_attributes
    assert "run_harness" in called_attributes
    assert "write_harness_run_outputs" in called_attributes
    assert {
        "sandbox_env",
        "preflight",
        "copy_source_tree",
        "install_graphify",
        "scenario_lifecycle_hooks",
        "build_validation_plan",
        "run_validation_plan",
    }.isdisjoint(called_attributes)


def test_sandbox_runner_main_composes_runtime_run_and_reporting_write(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    run_environment = SimpleNamespace(output=tmp_path / "out")
    run_result = SimpleNamespace(failed=0)

    def run_harness(args, environment, *, selected_target_name):
        calls.append(f"run-selected-target:{selected_target_name}")
        assert args.platform == "codex"
        assert environment is run_environment
        return run_result

    def write_harness_run_outputs(output, result):
        calls.append("write")
        assert output == run_environment.output
        assert result is run_result

    monkeypatch.setattr(sandbox_runner, "RUN_ENVIRONMENT", run_environment)
    monkeypatch.setattr(harness_orchestration, "run_harness", run_harness)
    monkeypatch.setattr(harness_run, "write_harness_run_outputs", write_harness_run_outputs)

    assert sandbox_runner.main(["--platform", "codex"]) == 0
    assert calls == ["run-selected-target:codex", "write"]


def test_sandbox_runner_direct_script_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "tools/install_sandbox/sandbox_runner.py", "--help"],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--platform" in result.stdout
    assert "--all" in result.stdout
    assert "--scope" in result.stdout
    assert "--copy-source" in result.stdout
    assert "--fail-fast-scenarios" in result.stdout


def test_sandbox_runner_module_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tools.install_sandbox.sandbox_runner", "--help"],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--platform" in result.stdout
    assert "--all" in result.stdout
    assert "--scope" in result.stdout
    assert "--copy-source" in result.stdout
    assert "--fail-fast-scenarios" in result.stdout


def test_sandbox_env_uses_isolated_home_xdg_project_and_path(monkeypatch, tmp_path) -> None:
    run_environment = SandboxRunEnvironment()
    home = tmp_path / "home"
    xdg = home / ".config"
    project = tmp_path / "project"
    repo_mount = tmp_path / "repo"
    src = tmp_path / "src"
    output = tmp_path / "out"
    monkeypatch.setitem(run_environment.runtime_roots, "home", home)
    monkeypatch.setitem(run_environment.runtime_roots, "xdg_config_home", xdg)
    monkeypatch.setitem(run_environment.runtime_roots, "project", project)
    monkeypatch.setitem(run_environment.runtime_roots, "repo_mount", repo_mount)
    monkeypatch.setitem(run_environment.runtime_roots, "src", src)
    monkeypatch.setitem(run_environment.runtime_roots, "output", output)
    monkeypatch.setenv("PATH", "/usr/bin")

    env = run_environment.sandbox_env()

    assert env["HOME"] == str(home)
    assert env["XDG_CONFIG_HOME"] == str(xdg)
    assert env["GRAPHIFY_PROJECT"] == str(project)
    assert env["GRAPHIFY_REPO_MOUNT"] == str(repo_mount)
    assert env["GRAPHIFY_SRC"] == str(src)
    assert env["GRAPHIFY_OUTPUT"] == str(output)
    assert "GRAPHIFY_USER_CWD" not in env
    assert env["PATH"].startswith(str(home / ".local" / "bin"))
    assert env["PATH"].endswith(":/usr/bin")


def test_preflight_uses_explicit_target_root_validation_owner(tmp_path) -> None:
    calls: list[tuple[str, set[str]]] = []

    class Registry:
        def validate_target_roots(self, declared_roots: set[str]) -> None:
            calls.append(("target", declared_roots))

        def validate_roots(self, declared_roots: set[str]) -> None:
            raise AssertionError("preflight should not use combined root validation when target owner exists")

    root_registry = SandboxRootRegistry(
        (
            SandboxRootSpec("home", str(tmp_path / "home"), reset=True),
            SandboxRootSpec("xdg_config_home", str(tmp_path / "home" / ".config")),
            SandboxRootSpec("project", str(tmp_path / "project"), reset=True),
            SandboxRootSpec("user_cwd", str(tmp_path / "user-cwd"), reset=True),
            SandboxRootSpec("repo_mount", str(tmp_path / "repo")),
            SandboxRootSpec("src", str(tmp_path / "src")),
            SandboxRootSpec("output", str(tmp_path / "out"), mount_mode="rw"),
        )
    )
    run_environment = SandboxRunEnvironment(root_registry=root_registry, scenario_registry=Registry())

    run_environment.preflight()

    assert calls == [("target", {"home", "project", "user_cwd"})]


def test_preflight_validates_registry_specific_synthetic_policy_roots(tmp_path) -> None:
    root_registry = SandboxRootRegistry(
        (
            SandboxRootSpec("home", str(tmp_path / "home"), reset=True),
            SandboxRootSpec("xdg_config_home", str(tmp_path / "home" / ".config")),
            SandboxRootSpec("project", str(tmp_path / "project"), reset=True),
            SandboxRootSpec("user_cwd", str(tmp_path / "user-cwd"), reset=True),
            SandboxRootSpec("repo_mount", str(tmp_path / "repo")),
            SandboxRootSpec("src", str(tmp_path / "src")),
            SandboxRootSpec("output", str(tmp_path / "out"), mount_mode="rw"),
        )
    )
    registry = validation_plan.InstallTargetCatalog(
        {
            "alpha": InstallTargetSpec(
                name="alpha",
                scopes={
                    "project": ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(ExpectedPath("project", "installed.txt"),),
                    )
                },
                universal_uninstall_scopes=("project",),
            )
        },
        universal_uninstall_specs=(
            UniversalUninstallScenarioSpec(
                scenario_id="custom-uninstall",
                platform_label="custom",
                scope="project",
                command=("tool", "uninstall"),
                cwd_root="missing-universal-root",
                eligible_target_scope="project",
            ),
        ),
        disposable_artifact_specs=(
            DisposableArtifactScenarioSpec(
                scenario_id="custom-disposable",
                platform_label="custom",
                scope="project",
                command=("tool", "purge"),
                cwd_root="project",
                artifact_subdir="custom-disposable",
                disposable_path_root="missing-disposable-root",
                disposable_path_relative="cache",
                seed_files=(),
                scope_eligibility=("project",),
                risk_note="custom disposable artifact policy",
            ),
        ),
    )
    run_environment = SandboxRunEnvironment(root_registry=root_registry, scenario_registry=registry)

    with pytest.raises(RuntimeError) as excinfo:
        run_environment.preflight()

    message = str(excinfo.value)
    assert "unknown harness policy root declaration" in message
    assert "missing-universal-root" in message
    assert "missing-disposable-root" in message


def test_preflight_preserves_root_path_and_invariant_keys(monkeypatch, tmp_path) -> None:
    root_registry = SandboxRootRegistry(
        (
            SandboxRootSpec("home", str(tmp_path / "home"), reset=True, preflight_required=True, sandbox_path_required=str(tmp_path / "home")),
            SandboxRootSpec(
                "xdg_config_home",
                str(tmp_path / "home" / ".config"),
                preflight_required=True,
                sandbox_path_required=str(tmp_path / "home" / ".config"),
            ),
            SandboxRootSpec("project", str(tmp_path / "project"), reset=True, preflight_required=True, sandbox_path_required=str(tmp_path / "project")),
            SandboxRootSpec("user_cwd", str(tmp_path / "user-cwd"), reset=True),
            SandboxRootSpec("repo_mount", str(tmp_path / "repo"), preflight_required=True, mount_mode="ro"),
            SandboxRootSpec("src", str(tmp_path / "src")),
            SandboxRootSpec("output", str(tmp_path / "out"), mount_mode="rw"),
        )
    )

    class Registry:
        def validate_target_roots(self, declared_roots: set[str]) -> None:
            assert declared_roots == {"home", "project", "user_cwd"}

    (tmp_path / "repo").mkdir()
    monkeypatch.setattr(sandbox_run_environment, "probe_read_only", lambda path: True)
    run_environment = SandboxRunEnvironment(root_registry=root_registry, scenario_registry=Registry())

    checks = run_environment.preflight()
    preflight_json = json.loads((tmp_path / "out" / "preflight.json").read_text(encoding="utf-8"))

    assert set(checks) == {
        "home",
        "xdg_config_home",
        "project",
        "user_cwd",
        "repo_mount",
        "src",
        "output",
        "home_is_sandbox",
        "xdg_is_sandbox",
        "project_is_sandbox",
        "repo_mount_exists",
        "repo_mount_read_only",
    }
    assert preflight_json == checks
    assert checks["repo_mount_exists"] is True
    assert checks["repo_mount_read_only"] is True


def test_preflight_current_policy_validation_uses_install_surface_roots_not_all_runtime_roots(tmp_path) -> None:
    root_registry = SandboxRootRegistry(
        (
            SandboxRootSpec("home", str(tmp_path / "home"), reset=True),
            SandboxRootSpec("xdg_config_home", str(tmp_path / "home" / ".config")),
            SandboxRootSpec("project", str(tmp_path / "project"), reset=True),
            SandboxRootSpec("user_cwd", str(tmp_path / "user-cwd"), reset=True),
            SandboxRootSpec("repo_mount", str(tmp_path / "repo")),
            SandboxRootSpec("src", str(tmp_path / "src")),
            SandboxRootSpec("output", str(tmp_path / "out"), mount_mode="rw"),
        )
    )
    registry = validation_plan.InstallTargetCatalog(
        {
            "alpha": InstallTargetSpec(
                name="alpha",
                scopes={
                    "project": ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(ExpectedPath("project", "installed.txt"),),
                    )
                },
                universal_uninstall_scopes=("project",),
            )
        },
        universal_uninstall_specs=(
            UniversalUninstallScenarioSpec(
                scenario_id="repo-mounted-uninstall",
                platform_label="repo-mounted",
                scope="project",
                command=("tool", "uninstall"),
                cwd_root="repo_mount",
                eligible_target_scope="project",
            ),
        ),
        disposable_artifact_specs=(),
    )
    run_environment = SandboxRunEnvironment(root_registry=root_registry, scenario_registry=registry)

    with pytest.raises(RuntimeError, match="repo_mount"):
        run_environment.preflight()


def test_main_characterizes_runner_order_and_output_boundary(monkeypatch, tmp_path) -> None:
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

    class RunEnvironmentDouble:
        harness_version = "2099-12-31.test"

        def __init__(self) -> None:
            self.output = output
            self.scenario_registry = Registry()

        def sandbox_env(self):
            calls.append("env")
            return {"HOME": "/tmp/graphify-home"}

        def preflight(self):
            calls.append("preflight")
            output.mkdir(parents=True, exist_ok=True)
            return {"project": "/tmp/graphify-project"}

        def copy_source_tree(self, copy_source):
            calls.append(f"copy:{copy_source}")
            return {"root": "/tmp/graphify-src", "copy_source_mode": copy_source}

        def install_graphify(self, env):
            calls.append("install-package")
            return {"version": "test", "install_mode": "normal"}

        def scenario_lifecycle_hooks(self):
            return object()

    class Registry:
        specs = {"codex": object()}

        def target_scenarios(self, platform_name: str, scope: str):
            return [scenario]

    run_environment = RunEnvironmentDouble()
    monkeypatch.setattr(sandbox_runner, "RUN_ENVIRONMENT", run_environment)
    plan = SimpleNamespace(requested_scope="project")

    def build_plan(registry, *, all_targets, target_name=None, scope="both", **kwargs):
        assert registry is run_environment.scenario_registry
        calls.append(f"plan:{target_name}:{scope}:{all_targets}")
        return plan

    monkeypatch.setattr(harness_orchestration.validation_plan, "build_validation_plan", build_plan)
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
    monkeypatch.setattr(harness_orchestration, "read_os_release", lambda: calls.append("os-release") or {"PRETTY_NAME": "Synthetic Linux"})
    monkeypatch.setattr(harness_orchestration.platform_mod, "machine", lambda: calls.append("architecture") or "synthetic-arch")

    original_write_manifest_json = reports.write_manifest_json
    original_write_summary = harness_orchestration.harness_run.agent_summary.write_summary

    def write_manifest(path, manifest):
        calls.append("write-manifest")
        original_write_manifest_json(path, manifest)

    def write_report(path, manifest):
        calls.append("write-report")
        Path(path).write_text("report\n", encoding="utf-8")

    def summarize_output(path):
        calls.append("summarize-output")
        return {"status": "FAIL", "failed_checks": [], "usage_guidance": "synthetic"}

    def write_summary(path, summary):
        calls.append("write-agent-summary")
        original_write_summary(path, summary)

    def print_summary(path, *, passed, failed):
        calls.append(f"stdout-summary:{passed}:{failed}")

    monkeypatch.setattr(reports, "write_manifest_json", write_manifest)
    monkeypatch.setattr(reports, "write_report_md", write_report)
    monkeypatch.setattr(harness_orchestration.harness_run.agent_summary, "summarize_output", summarize_output)
    monkeypatch.setattr(harness_orchestration.harness_run.agent_summary, "write_summary", write_summary)
    monkeypatch.setattr(reports, "print_summary", print_summary)

    def fake_harness_run_result(**kwargs):
        calls.append("harness-result")
        assert kwargs["plan"] is plan
        assert len(kwargs["results"]) == 1

        class FakeHarnessRunResult:
            passed = 0
            failed = 1

            def manifest(self) -> dict[str, object]:
                calls.append("manifest")
                return {
                    "harness_version": kwargs["harness_version"],
                    "python_version": kwargs["python_version"],
                    "os_release": kwargs["os_release"],
                    "architecture": kwargs["architecture"],
                    "graphify_version": kwargs["package_install"].get("version"),
                    "package_install": kwargs["package_install"],
                    "source_snapshot": kwargs["source_snapshot"],
                    "preflight": kwargs["preflight"],
                    "target_runtime_verification": {
                        "performed": False,
                        "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
                    },
                    "target_runtime_validation_sections": [{"section_title": "Synthetic Runtime", "status": "declared"}],
                    "target_coverage": [],
                    "target_coverage_summary": {},
                    "scenario_count": 1,
                    "graphify_file_effect_pass_count": 0,
                    "graphify_file_effect_fail_count": 1,
                    "pass_count": 0,
                    "fail_count": 1,
                    "results": kwargs["results"],
                    "risk_status_values": reporting_status.known_status_values(),
                }

        return FakeHarnessRunResult()

    monkeypatch.setattr(harness_orchestration.harness_run, "harness_run_result", fake_harness_run_result)

    exit_code = sandbox_runner.main(["--platform", "codex", "--scope", "project", "--copy-source", "auto", "--fail-fast-scenarios"])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert calls == [
        "env",
        "preflight",
        "copy:auto",
        "install-package",
        "plan:codex:project:False",
        "validation-plan:project:True",
        "os-release",
        "architecture",
        "harness-result",
        "manifest",
        "write-manifest",
        "write-report",
        "summarize-output",
        "write-agent-summary",
        "stdout-summary:0:1",
    ]
    assert (output / "report.md").read_text(encoding="utf-8") == "report\n"
    assert (output / "agent-summary.md").exists()
    assert json.loads((output / "agent-summary.json").read_text(encoding="utf-8"))["status"] == "FAIL"
    assert manifest["harness_version"] == run_environment.harness_version
    assert manifest["target_runtime_verification"] == {
        "performed": False,
        "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
    }
    assert manifest["target_runtime_validation_sections"] == [{"section_title": "Synthetic Runtime", "status": "declared"}]
    assert "target_tool_runtime" not in manifest
    assert "platforms" not in manifest
    assert "selected_targets" not in manifest
    assert "platform_coverage" not in manifest
    assert "platform_coverage_summary" not in manifest
    assert "coverage_records" not in manifest
    assert "runtime_limitation_sections" not in manifest
    assert manifest["scenario_count"] == len(manifest["results"])
    assert manifest["graphify_file_effect_fail_count"] == 1


def test_public_platform_intake_selects_validation_plan_target(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    calls: list[tuple[str, object]] = []

    class RunEnvironmentDouble:
        harness_version = "2099-12-31.test"
        scenario_registry = object()

        def __init__(self) -> None:
            self.output = output

        def sandbox_env(self):
            return {}

        def preflight(self):
            output.mkdir(parents=True, exist_ok=True)
            return {}

        def copy_source_tree(self, copy_source):
            return {"copy_source_mode": copy_source}

        def install_graphify(self, env):
            return {"version": "test"}

        def scenario_lifecycle_hooks(self):
            return object()

    run_environment = RunEnvironmentDouble()
    plan = SimpleNamespace(requested_scope="project", selected_targets=("codex",))

    def build_plan(registry, *, all_targets, target_name=None, scope="both", **kwargs):
        assert registry is run_environment.scenario_registry
        calls.append(("selected-target", target_name))
        return plan

    def run_validation_plan(plan_arg, env, hooks, fail_fast_scenarios=False):
        calls.append(("plan-selected-targets", plan_arg.selected_targets))
        return []

    monkeypatch.setattr(harness_orchestration.validation_plan, "build_validation_plan", build_plan)
    monkeypatch.setattr(scenario_lifecycle_plan, "run_validation_plan", run_validation_plan)
    monkeypatch.setattr(harness_orchestration, "read_os_release", lambda: {})
    monkeypatch.setattr(harness_orchestration.platform_mod, "machine", lambda: "synthetic-arch")

    args = sandbox_runner.parse_args(["--platform", "codex", "--scope", "project"])
    result = harness_orchestration.run_harness(args, run_environment, selected_target_name=args.platform)

    assert result.plan.selected_targets == ("codex",)
    assert calls == [
        ("selected-target", "codex"),
        ("plan-selected-targets", ("codex",)),
    ]


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

    class Plan:
        platforms = ("codex",)
        requested_scope = "project"
        standard_validation_count = 1
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
        target_coverage_summary = {
            "registered_target_count": 1,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 0,
        }
        target_runtime_verification = {"performed": False}

    plan = Plan()
    class RunEnvironmentDouble:
        harness_version = "2026-06-01.1"
        scenario_registry = object()

        def __init__(self) -> None:
            self.output = output

        def sandbox_env(self):
            return {"HOME": "/tmp/graphify-home"}

        def preflight(self):
            output.mkdir(parents=True, exist_ok=True)
            return {"project": "/tmp/graphify-project"}

        def copy_source_tree(self, copy_source):
            return {"root": "/tmp/graphify-src", "copy_source_mode": copy_source}

        def install_graphify(self, env):
            return {"version": "test", "install_mode": "normal"}

        def scenario_lifecycle_hooks(self):
            return object()

    monkeypatch.setattr(sandbox_runner, "RUN_ENVIRONMENT", RunEnvironmentDouble())
    monkeypatch.setattr(harness_orchestration.validation_plan, "build_validation_plan", lambda *args, **kwargs: plan)
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
    monkeypatch.setattr(harness_orchestration, "read_os_release", lambda: {"PRETTY_NAME": "Synthetic Linux"})
    monkeypatch.setattr(reports, "write_report_md", lambda path, manifest: Path(path).write_text("report\n", encoding="utf-8"))

    exit_code = sandbox_runner.main(["--platform", "codex", "--scope", "project"])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert manifest["scenario_count"] == 2
    assert manifest["graphify_file_effect_pass_count"] == 1
    assert manifest["graphify_file_effect_fail_count"] == 1
    assert manifest["pass_count"] == 1
    assert manifest["fail_count"] == 1
    assert manifest["target_coverage_summary"]["universal_scenario_count"] == 1


def test_install_graphify_version_probe_failure_is_precondition(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    source = tmp_path / "graphify-src"
    calls: list[str] = []
    run_environment = SandboxRunEnvironment()
    monkeypatch.setitem(run_environment.runtime_roots, "output", output)
    monkeypatch.setitem(run_environment.runtime_roots, "src", source)
    monkeypatch.setattr(source_snapshot, "read_installed_package_metadata", lambda package_name, source_path, *, home=None: {"installed_from_copied_source": True})

    def run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
        calls.append(command_class)
        if command_class == "package_install":
            return subprocess.CompletedProcess(list(command), 0, "installed", "")
        return subprocess.CompletedProcess(list(command), 1, "", "missing graphify")

    monkeypatch.setattr(command_runner, "run_capture", run_capture)

    with pytest.raises(RuntimeError, match="graphify version probe failed"):
        run_environment.install_graphify({})

    assert calls == ["package_install", "graphify_version"]


def test_install_graphify_rejects_wrong_package_provenance_after_probe(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    source = tmp_path / "graphify-src"
    run_environment = SandboxRunEnvironment()
    monkeypatch.setitem(run_environment.runtime_roots, "output", output)
    monkeypatch.setitem(run_environment.runtime_roots, "src", source)
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
        run_environment.install_graphify({})

    message = str(excinfo.value)
    assert "provenance check failed" in message
    assert "direct_url=" in message
    assert "expected_source=" in message


def test_runner_status_helpers_use_reporting_status_owner() -> None:
    run_environment = SandboxRunEnvironment()
    scenario = Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install", "--platform", "codex"),
        uninstall_command=None,
        cwd_root="project",
        expected=(ExpectedPath("project", "AGENTS.md"),),
    )

    report = run_environment.risk_report(scenario, True)

    assert reporting_status.combined_status(True) == reporting_status.RISK_GRAPHIFY_VERIFIED
    assert reporting_status.combined_status(False) == reporting_status.RISK_GRAPHIFY_FAILED
    assert (
        reporting_status.RISK_GRAPHIFY_VERIFIED
        == "graphify_install_verified"
    )
    assert (
        reporting_status.RISK_GRAPHIFY_FAILED
        == "graphify_install_failed"
    )
    assert (
        reports.known_status_values()
        == reporting_status.known_status_values()
    )
    assert report["statuses"] == [reporting_status.RISK_GRAPHIFY_VERIFIED]
    assert "target_tool_runtime_verified" not in report
