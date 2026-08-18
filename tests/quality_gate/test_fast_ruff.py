from __future__ import annotations

from pathlib import Path

from tests.quality_gate_support import PROJECT_ROOT, run_fast_gate, run_quality_gate


def test_fast_gate_accepts_corrected_ruff_fixture(tmp_path: Path) -> None:
    result = run_fast_gate(tmp_path, 'MESSAGE = "hello"\n')

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] ruff-format (exit 0)" in result.stdout
    assert "[PASS] ruff-lint (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("fast: PASS")


def test_fast_gate_reports_format_failure_after_running_lint(tmp_path: Path) -> None:
    result = run_fast_gate(tmp_path, "MESSAGE = 'hello'\n")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] ruff-format (exit 1)" in result.stdout
    assert "[PASS] ruff-lint (exit 0)" in result.stdout
    assert result.stdout.index("[PASS] ruff-lint") < result.stdout.index("fast: FAIL")


def test_fast_gate_rejects_lint_violation(tmp_path: Path) -> None:
    result = run_fast_gate(tmp_path, "import os\n")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[PASS] ruff-format (exit 0)" in result.stdout
    assert "F401" in result.stdout
    assert "[FAIL] ruff-lint (exit 1)" in result.stdout


def test_fast_gate_enforces_all_approved_complexity_limits(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
def classify(value: int) -> int:
    total = 0
    total += 1
    total += 2
    total += 3
    total += 4
    total += 5
    total += 6
    total += 7
    total += 8
    total += 9
    total += 10
    total += 11
    total += 12
    total += 13
    total += 14
    total += 15
    total += 16
    total += 17
    total += 18
    total += 19
    if value == 0:
        total += 1
    if value == 1:
        total += 1
    if value == 2:
        total += 1
    if value == 3:
        total += 1
    if value == 4:
        total += 1
    if value == 5:
        total += 1
    if value == 6:
        total += 1
    if value == 7:
        total += 1
    if value == 8:
        total += 1
    if value == 9:
        total += 1
    if value == 10:
        total += 1
    return total
""".lstrip(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "C901" in result.stdout
    assert "PLR0912" in result.stdout
    assert "PLR0915" in result.stdout


def test_fast_gate_does_not_offer_legacy_enum_disposition_to_new_code(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        """
from enum import Enum


class NewMode(str, Enum):
    ACTIVE = "active"
""".lstrip(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "UP042" in result.stdout
    assert "[FAIL] ruff-lint (exit 1)" in result.stdout


def test_fast_gate_reports_every_child_before_configuration_exit(tmp_path: Path) -> None:
    result = run_fast_gate(
        tmp_path,
        'MESSAGE = "hello"\n',
        ruff_config='target-version = "not-a-python-version"\n',
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] ruff-format (exit 2)" in result.stdout
    assert "[FAIL] ruff-lint (exit 2)" in result.stdout
    assert result.stdout.index("[FAIL] ruff-lint") < result.stdout.index(
        "fast: CONFIGURATION ERROR"
    )


def test_quality_gate_rejects_missing_command_as_invalid_usage() -> None:
    result = run_quality_gate(PROJECT_ROOT, arguments=())

    assert result.returncode == 2
    assert "the following arguments are required: command" in result.stderr
