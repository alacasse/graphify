from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tools.install_sandbox import run


def test_parse_args_requires_repo_and_platform_or_all(tmp_path: Path) -> None:
    args = run.parse_args(["--repo", str(tmp_path), "--platform", "codex", "--scope", "project"])

    assert args.repo == tmp_path
    assert args.platform == "codex"
    assert args.all is False
    assert args.scope == "project"


def test_run_cli_help_supports_direct_script_execution() -> None:
    repo = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "install_sandbox" / "run.py"), "--help"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Run Graphify install scenarios in an isolated Docker sandbox." in result.stdout
    assert "--repo" in result.stdout
    assert "--platform" in result.stdout
    assert "for example codex" not in result.stdout


def test_run_cli_names_platform_intake_as_selected_install_target_before_docker_command() -> None:
    tree = ast.parse(Path(run.__file__).read_text(encoding="utf-8"))
    main_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    selected_target_assignments = [
        node
        for node in ast.walk(main_node)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "selected_install_target_input" for target in node.targets)
    ]

    assert len(selected_target_assignments) == 1
    selected_target_assignment = selected_target_assignments[0]
    assert isinstance(selected_target_assignment.value, ast.Attribute)
    assert isinstance(selected_target_assignment.value.value, ast.Name)
    assert selected_target_assignment.value.value.id == "args"
    assert selected_target_assignment.value.attr == "platform"

    build_call = next(
        node
        for node in ast.walk(main_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "build_container_command"
    )
    platform_kwarg = next(keyword for keyword in build_call.keywords if keyword.arg == "platform")
    assert isinstance(platform_kwarg.value, ast.Name)
    assert platform_kwarg.value.id == "selected_install_target_input"


def test_run_cli_keeps_public_platform_flag_in_host_docker_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "out"
    build_container_kwargs: dict[str, object] = {}

    monkeypatch.setattr(run, "build_image_command", lambda *, runtime, image: ["docker", "build"])

    def fake_build_container_command(**kwargs: object) -> list[str]:
        build_container_kwargs.update(kwargs)
        return ["docker", "run", "graphify-install-sandbox", "--platform", str(kwargs["platform"])]

    monkeypatch.setattr(run, "build_container_command", fake_build_container_command)
    monkeypatch.setattr(run, "run_command", lambda command, *, timeout_seconds, command_class: None)
    monkeypatch.setattr(run, "write_and_print_agent_summary", lambda output: None)

    exit_code = run.main(["--repo", str(repo), "--platform", "codex", "--output", str(output)])

    assert exit_code == 0
    assert build_container_kwargs["platform"] == "codex"
    assert (output / "host-command.txt").read_text(encoding="utf-8").strip().endswith("--platform codex")


def test_run_cli_surfaces_agent_summary_on_container_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "out"

    monkeypatch.setattr(run, "build_image_command", lambda *, runtime, image: ["docker", "build"])
    monkeypatch.setattr(
        run,
        "build_container_command",
        lambda **kwargs: ["docker", "run", "graphify-install-sandbox"],
    )

    def fake_run_command(command: list[str], *, timeout_seconds: int, command_class: str) -> None:
        if command_class == "docker_run":
            raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(run, "run_command", fake_run_command)

    exit_code = run.main(["--repo", str(repo), "--platform", "codex", "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 7
    assert (output / "agent-summary.md").exists()
    assert "agent summary:" in captured.err
    assert "status: INCOMPLETE" in captured.err


def test_run_cli_surfaces_agent_summary_on_container_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "out"

    monkeypatch.setattr(run, "build_image_command", lambda *, runtime, image: ["docker", "build"])
    monkeypatch.setattr(
        run,
        "build_container_command",
        lambda **kwargs: ["docker", "run", "graphify-install-sandbox"],
    )

    def fake_run_command(command: list[str], *, timeout_seconds: int, command_class: str) -> None:
        if command_class == "docker_run":
            output.mkdir(parents=True, exist_ok=True)
            (output / "manifest.json").write_text('{"results":[],"scenario_count":0}\n', encoding="utf-8")

    monkeypatch.setattr(run, "run_command", fake_run_command)

    exit_code = run.main(["--repo", str(repo), "--platform", "codex", "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (output / "agent-summary.md").exists()
    assert "agent summary:" in captured.err
    assert "status: PASS" in captured.err
