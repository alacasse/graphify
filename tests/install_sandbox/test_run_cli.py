from __future__ import annotations

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
