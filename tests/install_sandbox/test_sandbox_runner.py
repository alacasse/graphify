from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.install_sandbox import command_runner, reports, sandbox_runner, scenario_lifecycle, source_snapshot
from tools.install_sandbox.platform_specs import ExpectedPath, Scenario


def test_parse_args_requires_platform_or_all() -> None:
    args = sandbox_runner.parse_args(["--platform", "codex", "--scope", "project", "--copy-source", "auto", "--fail-fast-scenarios"])

    assert args.platform == "codex"
    assert args.all is False
    assert args.scope == "project"
    assert args.copy_source == "auto"
    assert args.fail_fast_scenarios is True


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


def test_selected_scenarios_projects_platform_registry_selection(monkeypatch) -> None:
    scenario = Scenario(
        platform="unit",
        scope="project",
        install_command=("graphify", "install", "--platform", "unit"),
        uninstall_command=None,
        cwd_root="project",
        expected=(ExpectedPath("project", "unit.md"),),
    )
    class Registry:
        def selected_platforms(self, *, all_platforms: bool, platform_name: str | None) -> list[str]:
            return ["unit"]

        def platform_scenarios(self, platform_name: str, scope: str):
            return [scenario]

    registry = Registry()
    monkeypatch.setattr(sandbox_runner, "SCENARIO_REGISTRY", registry)
    args = sandbox_runner.parse_args(["--platform", "unit", "--scope", "project"])

    assert sandbox_runner.selected_scenarios(args) == [scenario]


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
        def selected_platforms(self, *, all_platforms: bool, platform_name: str | None) -> list[str]:
            return ["codex"]

        def platform_scenarios(self, platform_name: str, scope: str):
            return [scenario]

        def coverage_records(self, platforms: list[str], scope: str):
            return []

    monkeypatch.setattr(sandbox_runner, "SCENARIO_REGISTRY", Registry())
    monkeypatch.setattr(
        scenario_lifecycle,
        "run_matrix_scenarios",
        lambda platforms, scope, env, *, hooks, fail_fast_scenarios=False: calls.append(f"matrix:{scope}:{fail_fast_scenarios}")
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
    assert calls == ["env", "preflight", "copy:auto", "install-package", "matrix:project:True"]
    assert (output / "report.md").read_text(encoding="utf-8") == "report\n"
    assert manifest["target_runtime_verification"] == {
        "performed": False,
        "reason": "Tier 1 sandbox validates Graphify-owned installer file effects only.",
    }
    assert "target_tool_runtime" not in manifest
    assert manifest["graphify_file_effect_fail_count"] == 1
    assert manifest["platform_coverage_summary"]["runnable_scope_count"] == 1


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
    assert report["statuses"] == [sandbox_runner.RISK_GRAPHIFY_VERIFIED]
    assert "target_tool_runtime_verified" not in report
