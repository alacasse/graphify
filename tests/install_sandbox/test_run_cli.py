from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
