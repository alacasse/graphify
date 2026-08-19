"""Shared black-box fixture support for install-sandbox quality-gate tests."""

from __future__ import annotations

import json
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


def copy_live_install_sandbox_gate_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "repository"
    shutil.copytree(
        PROJECT_ROOT / "tools" / "install_sandbox",
        fixture_root / "tools" / "install_sandbox",
        ignore=shutil.ignore_patterns("__pycache__", "graphify-out", "out"),
    )
    workflow = Path(".github/workflows/install-sandbox.yml")
    (fixture_root / workflow).parent.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / workflow, fixture_root / workflow)
    (fixture_root / ".venv").symlink_to(PROJECT_ROOT / ".venv", target_is_directory=True)
    shutil.copyfile(RUFF_CONFIG, fixture_root / RUFF_CONFIG.name)
    shutil.copyfile(PYRIGHT_CONFIG, fixture_root / PYRIGHT_CONFIG.name)
    return fixture_root


def copy_install_sandbox_gate_fixture(tmp_path: Path) -> Path:
    """Build the immutable closed-baseline state used by applicability proofs."""
    fixture_root = tmp_path / "repository"
    production = fixture_root / "tools/install_sandbox"
    production.mkdir(parents=True)
    sources = {
        "__init__.py": '"""Fixed gate-installation fixture."""\n',
        "ci_result.py": "def main() -> int:\n    return 0\n",
        "docker.py": "def run_sandbox() -> None:\n    return None\n",
        "effects.py": '"""Legacy fixture module."""\n',
        "lifecycle.py": '"""Legacy fixture module."""\n',
        "models.py": '"""Legacy fixture module."""\n',
        "reporting.py": '"""Legacy fixture module."""\n',
        "run.py": (
            "from tools.install_sandbox.docker import run_sandbox\n"
            "from tools.install_sandbox.run_artifacts import write_run\n"
            "from tools.install_sandbox.specs import load_specs\n\n\n"
            "def main() -> int:\n"
            "    run_sandbox()\n"
            "    write_run()\n"
            "    load_specs()\n"
            "    return 0\n"
        ),
        "run_artifacts.py": "def write_run() -> None:\n    return None\n",
        "sandbox_runner.py": "def main() -> int:\n    return 0\n",
        "specs.py": "def load_specs() -> None:\n    return None\n",
    }
    for name, source in sources.items():
        (production / name).write_text(source, encoding="utf-8")
    specs = production / "specs"
    specs.mkdir()
    (specs / "catalog.yaml").write_text("targets: {}\n", encoding="utf-8")
    (production / "Dockerfile").write_text(
        'FROM python:3.12-slim\nENTRYPOINT ["python", "-m", '
        '"tools.install_sandbox.sandbox_runner"]\n',
        encoding="utf-8",
    )

    workflow = fixture_root / ".github/workflows/install-sandbox.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Install sandbox fixture\n"
        "jobs:\n"
        "  proof:\n"
        "    steps:\n"
        "      - run: |\n"
        "          python tools/install_sandbox/run.py \\\n"
        "            --repo . \\\n"
        "            --all \\\n"
        "            --scope both \\\n"
        "            --output out\n"
        "      - run: python -m tools.install_sandbox.ci_result\n",
        encoding="utf-8",
    )
    (fixture_root / RUFF_CONFIG.name).write_text(
        'target-version = "py312"\n'
        "line-length = 100\n"
        "preview = false\n\n"
        "[lint]\n"
        'select = ["E", "F", "I", "UP", "B", "SIM", "RUF", '
        '"C901", "PLR0912", "PLR0915"]\n\n'
        "[lint.mccabe]\n"
        "max-complexity = 8\n\n"
        "[lint.pylint]\n"
        "max-branches = 10\n"
        "max-statements = 30\n",
        encoding="utf-8",
    )
    analysis_paths = [
        "tools/install_sandbox",
        "tests/install_sandbox/unit",
        "tests/install_sandbox/component",
        "tests/install_sandbox/behavioral",
    ]
    (fixture_root / PYRIGHT_CONFIG.name).write_text(
        json.dumps(
            {
                "include": analysis_paths,
                "strict": analysis_paths,
                "pythonVersion": PYTHON_VERSION,
                "typeCheckingMode": "basic",
                "venvPath": ".",
                "venv": ".venv",
            }
        ),
        encoding="utf-8",
    )
    (fixture_root / ".venv").symlink_to(PROJECT_ROOT / ".venv", target_is_directory=True)
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
    fixture_root = copy_live_install_sandbox_gate_fixture(tmp_path)
    production = fixture_root / "tools" / "install_sandbox"
    if filename == "reporting.py":
        source += (
            "\n\ndef build_manifest(*args: object, **kwargs: object) -> dict[str, object]:\n"
            "    return {}\n\n\n"
            "def write_run_outputs(*args: object, **kwargs: object) -> None:\n"
            "    return None\n"
        )
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
