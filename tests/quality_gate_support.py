"""Shared black-box fixture support for install-sandbox quality-gate tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.install_sandbox_quality_policy import PYTHON_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCRIPT = PROJECT_ROOT / "scripts" / "install_sandbox_quality.py"
RUFF_CONFIG = PROJECT_ROOT / "ruff.install-sandbox.toml"
PYRIGHT_CONFIG = PROJECT_ROOT / "pyrightconfig.install-sandbox.json"
LOCKFILE = PROJECT_ROOT / "uv.lock"
FROZEN_PYTHON_RUN = ("uv", "run", "--frozen", "--python", PYTHON_VERSION)


def run_quality_gate(
    repository: Path,
    *,
    arguments: tuple[str, ...] = ("fast",),
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["UV_PROJECT"] = str(PROJECT_ROOT)
    return subprocess.run(
        [
            *FROZEN_PYTHON_RUN,
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


def copy_install_sandbox_gate_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "repository"
    shutil.copytree(
        PROJECT_ROOT / "tools" / "install_sandbox",
        fixture_root / "tools" / "install_sandbox",
    )
    shutil.copyfile(RUFF_CONFIG, fixture_root / RUFF_CONFIG.name)
    shutil.copyfile(PYRIGHT_CONFIG, fixture_root / PYRIGHT_CONFIG.name)
    return fixture_root


def run_fast_gate(
    tmp_path: Path,
    source: str,
    *,
    ruff_config: str | None = None,
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
    if ruff_config is None:
        shutil.copyfile(RUFF_CONFIG, fixture_ruff_config)
    else:
        fixture_ruff_config.write_text(ruff_config, encoding="utf-8")
    fixture_pyright_config = fixture_root / PYRIGHT_CONFIG.name
    if pyright_config is None:
        shutil.copyfile(PYRIGHT_CONFIG, fixture_pyright_config)
    else:
        fixture_pyright_config.write_text(pyright_config, encoding="utf-8")

    return run_quality_gate(fixture_root)
