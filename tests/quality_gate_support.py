"""Shared black-box fixture support for install-sandbox quality-gate tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCRIPT = PROJECT_ROOT / "scripts" / "install_sandbox_quality.py"
RUFF_CONFIG = PROJECT_ROOT / "ruff.install-sandbox.toml"
PYRIGHT_CONFIG = PROJECT_ROOT / "pyrightconfig.install-sandbox.json"
LOCKFILE = PROJECT_ROOT / "uv.lock"


def run_quality_gate(
    repository: Path,
    *,
    arguments: tuple[str, ...] = ("fast",),
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["UV_PROJECT"] = str(PROJECT_ROOT)
    return subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "python",
            str(QUALITY_SCRIPT),
            *arguments,
        ],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def run_fast_gate(
    tmp_path: Path,
    source: str,
    *,
    config: str | None = None,
    filename: str = "reporting.py",
    replacement_source: str | None = None,
    pyright_config: str | None = None,
    bandit_config: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture_root = tmp_path / "repository"
    production = fixture_root / "tools" / "install_sandbox"
    production.mkdir(parents=True)
    (production / filename).write_text(source, encoding="utf-8")

    if replacement_source is not None:
        unit_tests = fixture_root / "tests" / "install_sandbox" / "unit"
        unit_tests.mkdir(parents=True)
        (unit_tests / "test_fixture.py").write_text(replacement_source, encoding="utf-8")
    if bandit_config is not None:
        (production / ".bandit").write_text(bandit_config, encoding="utf-8")

    fixture_ruff_config = fixture_root / RUFF_CONFIG.name
    if config is None:
        shutil.copyfile(RUFF_CONFIG, fixture_ruff_config)
    else:
        fixture_ruff_config.write_text(config, encoding="utf-8")
    fixture_pyright_config = fixture_root / PYRIGHT_CONFIG.name
    if pyright_config is None:
        shutil.copyfile(PYRIGHT_CONFIG, fixture_pyright_config)
    else:
        fixture_pyright_config.write_text(pyright_config, encoding="utf-8")

    return run_quality_gate(fixture_root)
