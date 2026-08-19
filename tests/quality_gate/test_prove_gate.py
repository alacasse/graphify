from pathlib import Path

from tests.quality_gate_support import (
    PROJECT_ROOT,
    copy_prove_gate_fixture,
    run_prove_gate,
    run_quality_gate,
)

PROOF_MARKER = "install_sandbox_proof"


def _proof_commands(commands: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(command for command in commands if command and command[0] == "pytest")


def test_prove_runs_the_declared_operational_proof_suite() -> None:
    result = run_quality_gate(PROJECT_ROOT, arguments=("prove",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] prove-configuration" in result.stdout
    assert "[PASS] operational-proof (exit 0)" in result.stdout
    assert "[PASS] dependency-lock" in result.stdout
    assert result.stdout.rstrip().endswith("prove: PASS")


def test_prove_detects_lock_drift_after_the_proof_child(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)

    result, _ = run_prove_gate(
        tmp_path,
        repository,
        command_rules={
            "pytest": {
                "stdout": "99 passed",
                "lock_contents": "changed lock\n",
            }
        },
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[PASS] operational-proof (exit 0)" in result.stdout
    assert "[FAIL] dependency-lock (exit 1)" in result.stdout
    assert "uv.lock changed during prove" in result.stderr
    assert result.stdout.rstrip().endswith("prove: FAIL")


def test_prove_invokes_only_marked_operational_proofs(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)

    result, commands = run_prove_gate(tmp_path, repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _proof_commands(commands) == (
        (
            "pytest",
            "tests/quality_gate",
            "-m",
            PROOF_MARKER,
            "-q",
            "--tb=short",
            "--strict-config",
            "--strict-markers",
            "-W",
            "error",
        ),
    )


def test_prove_reports_an_incomplete_inventory_without_suppressing_proof(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)
    proof_module = repository / "tests/quality_gate/test_fast_ruff.py"
    proof_module.write_text(
        proof_module.read_text(encoding="utf-8").replace(
            '@pytest.mark.install_sandbox_proof("formatting-violation")\n',
            "",
        ),
        encoding="utf-8",
    )

    result, commands = run_prove_gate(tmp_path, repository)

    assert result.returncode == 2, result.stdout + result.stderr
    assert _proof_commands(commands)
    assert "missing required proof scenarios" in result.stderr
    assert "formatting violation" in result.stderr
    assert "[PASS] operational-proof (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: CONFIGURATION ERROR")


def test_prove_reports_an_unknown_requirement_without_suppressing_proof(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)
    (repository / "tests/quality_gate/test_unreviewed_proof.py").write_text(
        "import pytest\n\n"
        '@pytest.mark.install_sandbox_proof("unreviewed-requirement")\n'
        "def test_unreviewed() -> None:\n    assert True\n",
        encoding="utf-8",
    )

    result, commands = run_prove_gate(tmp_path, repository)

    assert result.returncode == 2, result.stdout + result.stderr
    assert _proof_commands(commands)
    assert "unknown proof requirements: unreviewed-requirement" in result.stderr
    assert "[PASS] operational-proof (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: CONFIGURATION ERROR")


def test_prove_reports_a_missing_lock_without_suppressing_proof(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)
    (repository / "uv.lock").unlink()

    result, commands = run_prove_gate(tmp_path, repository)

    assert result.returncode == 2, result.stdout + result.stderr
    assert _proof_commands(commands)
    assert "unable to read uv.lock" in result.stderr
    assert "[PASS] operational-proof (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: CONFIGURATION ERROR")


def test_prove_does_not_treat_test_names_as_contract(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)
    proof_module = repository / "tests/quality_gate/test_fast_ruff.py"
    proof_module.write_text(
        proof_module.read_text(encoding="utf-8").replace(
            "def test_fast_gate_reports_format_failure_after_running_lint(",
            "def test_removed_format_proof_scenario(",
        ),
        encoding="utf-8",
    )

    result, commands = run_prove_gate(tmp_path, repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _proof_commands(commands)
    assert "missing required proof scenarios" not in result.stderr
    assert result.stdout.rstrip().endswith("prove: PASS")


def test_prove_preserves_a_proof_failure(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)

    result, _ = run_prove_gate(
        tmp_path,
        repository,
        command_rules={"pytest": {"exit": 1, "stderr": "deliberate proof failure"}},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "deliberate proof failure" in result.stderr
    assert "[FAIL] operational-proof (exit 1)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: FAIL")


def test_prove_preserves_a_pytest_configuration_exit(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)

    result, _ = run_prove_gate(
        tmp_path,
        repository,
        command_rules={"pytest": {"exit": 2, "stderr": "invalid pytest configuration"}},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid pytest configuration" in result.stderr
    assert "[FAIL] operational-proof (exit 2)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: CONFIGURATION ERROR")


def test_prove_preserves_the_approved_timeout_exit(tmp_path: Path) -> None:
    repository = copy_prove_gate_fixture(tmp_path)

    result, _ = run_prove_gate(
        tmp_path,
        repository,
        command_rules={"pytest": {"exit": 124, "stderr": "proof child timed out"}},
    )

    assert result.returncode == 124, result.stdout + result.stderr
    assert "proof child timed out" in result.stderr
    assert "[FAIL] operational-proof (exit 124)" in result.stdout
    assert result.stdout.rstrip().endswith("prove: TIMEOUT")
