from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

from tests.quality_gate_support import (
    LOCKFILE,
    PROJECT_ROOT,
    PYRIGHT_CONFIG,
    RUFF_CONFIG,
    run_fast_gate,
    run_quality_gate,
)


def test_fast_gate_rejects_strict_type_error(tmp_path: Path) -> None:
    result = run_fast_gate(tmp_path, "VALUE: str = 1\n")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "reportAssignmentType" in result.stdout
    assert "[FAIL] pyright (exit 1)" in result.stdout
    assert result.stdout.rstrip().endswith("fast: FAIL")


def test_fast_gate_rejects_file_level_typing_downgrade(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
# pyright: basic


def identity(value):
    return value
""".lstrip(),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "unapproved Pyright directive" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_rejects_blocking_security_finding(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
import hashlib

hashlib.md5(b"secret").hexdigest()
""".lstrip(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "B324" in result.stdout
    assert "[FAIL] bandit (exit 1)" in result.stdout
    assert result.stdout.rstrip().endswith("fast: FAIL")


def test_fast_gate_rejects_discovered_bandit_configuration(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
import hashlib

hashlib.md5(b"secret").hexdigest()
""".lstrip(),
        bandit_config="[bandit]\nskips = B324\n",
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "discovered Bandit configuration is not permitted" in result.stderr
    assert "[FAIL] bandit (exit 2)" in result.stdout


def test_fast_gate_accepts_approved_baseline_without_changing_lock() -> None:
    before = LOCKFILE.read_bytes()

    result = run_quality_gate(PROJECT_ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] pyright (exit 0)" in result.stdout
    assert "[PASS] bandit (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("fast: PASS")
    assert LOCKFILE.read_bytes() == before


def test_fast_gate_rejects_new_production_file_outside_strict_scope(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        filename="new_module.py",
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "strict scope does not cover tools/install_sandbox/new_module.py" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout
    assert "[PASS] bandit (exit 0)" in result.stdout
    assert result.stdout.index("[PASS] bandit") < result.stdout.index("fast: CONFIGURATION ERROR")


def test_fast_gate_rejects_relaxed_replacement_test_typing_scope(tmp_path: Path) -> None:
    config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
    config["strict"].remove("tests/install_sandbox/unit")

    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        pyright_config=json.dumps(config),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "strict scope does not cover tests/install_sandbox/unit" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_rejects_typing_exclusion_of_production(tmp_path: Path) -> None:
    config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
    config["exclude"] = ["tools/install_sandbox/reporting.py"]

    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        pyright_config=json.dumps(config),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "unapproved settings: exclude" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_rejects_relaxed_legacy_basic_mode(tmp_path: Path) -> None:
    config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
    config["typeCheckingMode"] = "off"

    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        pyright_config=json.dumps(config),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "default typing mode must remain basic" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_rejects_removed_production_analysis_scope(tmp_path: Path) -> None:
    config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
    config["include"].remove("tools/install_sandbox")

    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        pyright_config=json.dumps(config),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "analysis scope does not cover tools/install_sandbox" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_rejects_pyright_runtime_drift(tmp_path: Path) -> None:
    config = json.loads(PYRIGHT_CONFIG.read_text(encoding="utf-8"))
    config["pythonVersion"] = "3.10"

    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        pyright_config=json.dumps(config),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Pyright runtime must remain Python 3.12" in result.stderr
    assert "[FAIL] pyright (exit 2)" in result.stdout


def test_fast_gate_requires_changed_legacy_file_to_enter_strict_scope(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repository"
    production = fixture_root / "tools" / "install_sandbox"
    shutil.copytree(PROJECT_ROOT / "tools" / "install_sandbox", production)
    shutil.copyfile(RUFF_CONFIG, fixture_root / RUFF_CONFIG.name)
    shutil.copyfile(PYRIGHT_CONFIG, fixture_root / PYRIGHT_CONFIG.name)
    legacy = production / "ci_result.py"
    legacy.write_text(
        legacy.read_text(encoding="utf-8") + '\nMATERIAL_CHANGE: str = "changed"\n',
        encoding="utf-8",
    )

    result = run_quality_gate(fixture_root)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "changed legacy typing file is not strict: tools/install_sandbox/ci_result.py" in (
        result.stderr
    )
    assert "[FAIL] pyright (exit 2)" in result.stdout
    assert "[PASS] bandit (exit 0)" in result.stdout


def test_fast_gate_applies_strict_typing_to_replacement_tests(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        'MESSAGE: str = "hello"\n',
        replacement_source="""
def identity(value):
    return value
""".lstrip(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "tests/install_sandbox/unit/test_fixture.py" in result.stdout
    assert "reportMissingParameterType" in result.stdout
    assert "[FAIL] pyright (exit 1)" in result.stdout


def test_fast_gate_does_not_offer_legacy_temp_root_disposition_to_new_code(
    tmp_path: Path,
) -> None:
    result = run_fast_gate(tmp_path, 'TEMP_ROOT = "/tmp/replacement"\n')

    assert result.returncode == 1, result.stdout + result.stderr
    assert "B108" in result.stdout
    assert "[FAIL] bandit (exit 1)" in result.stdout


def test_fast_gate_rejects_new_security_disposition(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        'TEMP_ROOT = "/tmp/replacement"  # nosec B108\n',
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "unapproved Bandit disposition" in result.stderr
    assert "[FAIL] bandit (exit 2)" in result.stdout


def test_fast_gate_rejects_compact_nosec_spelling(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        'TEMP_ROOT = "/tmp/replacement"  #nosec B108\n',
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "unapproved Bandit disposition" in result.stderr
    assert "[FAIL] bandit (exit 2)" in result.stdout


def test_fast_gate_reports_typing_and_security_failures_independently(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
import hashlib

VALUE: str = 1
hashlib.md5(b"secret").hexdigest()
""".lstrip(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] pyright (exit 1)" in result.stdout
    assert "[FAIL] bandit (exit 1)" in result.stdout
    assert result.stdout.index("[FAIL] pyright") < result.stdout.index("[FAIL] bandit")
    assert result.stdout.index("[FAIL] bandit") < result.stdout.index("fast: FAIL")


def test_fast_gate_allows_security_findings_below_approved_severity(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
import subprocess

subprocess.run(["true"], check=False)
""".lstrip(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] bandit (exit 0)" in result.stdout


def test_approved_pyyaml_stubs_are_declared_and_locked_exactly() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    development = project["dependency-groups"]["dev"]
    declarations = [value for value in development if value.lower().startswith("types-pyyaml")]
    lock = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    locked = [package for package in lock["package"] if package["name"] == "types-pyyaml"]

    assert declarations == ["types-pyyaml>=6.0.12.20260518"]
    assert [package["version"] for package in locked] == ["6.0.12.20260518"]
