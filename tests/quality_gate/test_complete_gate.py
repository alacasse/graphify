from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.quality_gate_support import PYRIGHT_CONFIG, copy_complete_gate_fixture, run_complete_gate


def _commands_with_executable(
    commands: tuple[tuple[str, ...], ...], executable: str
) -> tuple[tuple[str, ...], ...]:
    return tuple(command for command in commands if command and command[0] == executable)


def _add_replacement_production(repository: Path) -> None:
    source = repository / "tools/install_sandbox/control_plane/request.py"
    source.parent.mkdir(parents=True)
    source.write_text("def run() -> int:\n    return 0\n", encoding="utf-8")
    config_path = repository / PYRIGHT_CONFIG.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strict"].append("tools/install_sandbox/control_plane")
    config_path.write_text(json.dumps(config), encoding="utf-8")


def _add_evidence(repository: Path, evidence_class: str) -> None:
    test = repository / f"tests/install_sandbox/{evidence_class}/test_{evidence_class}.py"
    test.parent.mkdir(parents=True)
    test.write_text(
        f"def test_{evidence_class}() -> None:\n    assert True\n",
        encoding="utf-8",
    )


def _convert_to_atomic_cutover(repository: Path) -> None:
    production = repository / "tools/install_sandbox"
    classifier = (production / "ci_result.py").read_text(encoding="utf-8")
    for name in (
        "ci_result.py",
        "docker.py",
        "effects.py",
        "lifecycle.py",
        "models.py",
        "reporting.py",
        "run_artifacts.py",
        "sandbox_runner.py",
        "specs.py",
    ):
        (production / name).unlink()

    run_path = production / "run.py"
    legacy_runner = run_path.read_text(encoding="utf-8")
    runtime = legacy_runner[legacy_runner.index("import argparse") :]
    run_path.write_text(
        "from __future__ import annotations\n\n"
        "if False:\n"
        "    from tools.install_sandbox.control_plane import request\n\n"
        "    request.run()\n\n" + runtime,
        encoding="utf-8",
    )
    (production / "ci.py").write_text(classifier, encoding="utf-8")
    entrypoint = production / "container/entrypoint.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (production / "Dockerfile").unlink()
    (production / "Containerfile").write_text(
        'ENTRYPOINT ["python", "-m", "tools.install_sandbox.container.entrypoint"]\n',
        encoding="utf-8",
    )

    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "tools.install_sandbox.ci_result",
            "tools.install_sandbox.ci",
        ),
        encoding="utf-8",
    )
    config_path = repository / PYRIGHT_CONFIG.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strict"] = [
        "tools/install_sandbox",
        "tests/install_sandbox/unit",
        "tests/install_sandbox/component",
        "tests/install_sandbox/behavioral",
    ]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "complete-gate-fixture"\nversion = "0"\n',
        encoding="utf-8",
    )


def test_complete_gate_runs_every_gate_installation_responsibility(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    original_lock = (repository / "uv.lock").read_bytes()

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: gate installation" in result.stdout
    assert "[NOT APPLICABLE] unit-evidence" in result.stdout
    assert "[NOT APPLICABLE] component-evidence" in result.stdout
    assert "[NOT APPLICABLE] behavioral-evidence" in result.stdout
    assert "[NOT APPLICABLE] replacement-coverage" in result.stdout
    assert "[PASS] coverage-policy" in result.stdout
    assert "[PASS] dependency-audit (exit 0)" in result.stdout
    assert "[PASS] repository-suite (exit 0)" in result.stdout
    assert "[PASS] docker-runner (exit 0)" in result.stdout
    assert "[PASS] docker-classifier (exit 0)" in result.stdout
    assert "[PASS] dependency-lock" in result.stdout
    assert result.stdout.rstrip().endswith("complete: PASS")

    assert _commands_with_executable(commands, "ruff")
    assert _commands_with_executable(commands, "pyright")
    assert _commands_with_executable(commands, "bandit")
    assert _commands_with_executable(commands, "pip-audit") == (
        ("pip-audit", "--strict", "--progress-spinner", "off"),
    )
    assert _commands_with_executable(commands, "pytest") == (
        (
            "pytest",
            "tests/",
            "-q",
            "--tb=short",
            "--strict-config",
            "--strict-markers",
            "-W",
            "error",
            "--ignore=tests/install_sandbox/unit",
            "--ignore=tests/install_sandbox/component",
            "--ignore=tests/install_sandbox/behavioral",
        ),
    )
    docker_commands = tuple(
        command for command in commands if "tools/install_sandbox/run.py" in command
    )
    assert len(docker_commands) == 1
    assert "--all" in docker_commands[0]
    assert "--scope" in docker_commands[0]
    assert "both" in docker_commands[0]
    assert (repository / "uv.lock").read_bytes() == original_lock


def test_complete_gate_replaces_fast_evidence_with_branch_coverage_during_construction(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: replacement construction" in result.stdout
    assert "[PASS] unit-evidence-collection (exit 0)" in result.stdout
    assert "[PASS] component-evidence-collection (exit 0)" in result.stdout
    assert "[PASS] replacement-coverage (exit 0)" in result.stdout
    assert "[NOT APPLICABLE] behavioral-evidence" in result.stdout

    pytest_commands = _commands_with_executable(commands, "pytest")
    coverage_commands = tuple(command for command in pytest_commands if "--cov-branch" in command)
    assert coverage_commands == (
        (
            "pytest",
            "tests/install_sandbox/unit",
            "tests/install_sandbox/component",
            "-q",
            "--tb=short",
            "--strict-config",
            "--strict-markers",
            "-W",
            "error",
            "--cov=tools.install_sandbox",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-fail-under=90",
        ),
    )
    assert not any(
        command[:3]
        == (
            "pytest",
            "tests/install_sandbox/unit",
            "tests/install_sandbox/component",
        )
        and "--cov-branch" not in command
        for command in pytest_commands
    )


def test_complete_gate_rejects_repository_suite_warnings(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        command_rules={"pytest tests/": {"stdout": "1 passed, 1 warning"}},
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] repository-suite (exit 1)" in result.stdout
    assert "repository suite produced warnings" in result.stderr
    assert _commands_with_executable(commands, "pip-audit")
    assert any("tools/install_sandbox/run.py" in command for command in commands)
    assert result.stdout.rstrip().endswith("complete: FAIL")


def test_complete_gate_preserves_repository_suite_environment_skips(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, _ = run_complete_gate(
        tmp_path,
        repository,
        command_rules={"pytest tests/": {"stdout": "1 passed, 1 skipped"}},
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] repository-suite (exit 0)" in result.stdout


def test_complete_gate_runs_all_evidence_and_remaining_tree_coverage_at_cutover(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: atomic cutover" in result.stdout
    assert "[PASS] coverage-policy" in result.stdout
    assert "[PASS] replacement-coverage (exit 0)" in result.stdout
    assert "[PASS] behavioral-evidence (exit 0)" in result.stdout
    pytest_commands = _commands_with_executable(commands, "pytest")
    assert any("--cov=tools.install_sandbox" in command for command in pytest_commands)
    assert any(
        command[:2] == ("pytest", "tests/install_sandbox/behavioral")
        and "--collect-only" not in command
        for command in pytest_commands
    )
    classifier_commands = tuple(command for command in commands if command[:2] == ("python", "-m"))
    assert classifier_commands == (
        (
            "python",
            "-m",
            "tools.install_sandbox.ci",
            "--run-json",
            classifier_commands[0][4],
            "--runner-exit-code",
            "0",
        ),
    )


def test_complete_gate_rejects_a_replacement_path_in_legacy_coverage_exclusions(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    pyproject = repository / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            '    "tools/install_sandbox/specs.py",\n',
            '    "tools/install_sandbox/specs.py",\n'
            '    "tools/install_sandbox/control_plane/request.py",\n',
        ),
        encoding="utf-8",
    )

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] coverage-policy (exit 2)" in result.stdout
    assert "coverage exclusions must be the exact legacy retirement list" in result.stderr
    assert any("--cov-branch" in command for command in commands)
    assert _commands_with_executable(commands, "pip-audit")
    assert any("tools/install_sandbox/run.py" in command for command in commands)
    assert result.stdout.rstrip().endswith("complete: CONFIGURATION ERROR")


def test_complete_gate_rejects_legacy_coverage_exclusions_at_cutover(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    legacy_pyproject = (repository / "pyproject.toml").read_text(encoding="utf-8")
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    (repository / "pyproject.toml").write_text(legacy_pyproject, encoding="utf-8")
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] coverage-policy (exit 2)" in result.stdout
    assert "coverage exclusions must be empty at Atomic Cutover" in result.stderr
    assert any("--cov-branch" in command for command in commands)
    assert any(command[:3] == ("python", "-m", "tools.install_sandbox.ci") for command in commands)


def test_complete_gate_preserves_independent_failures_before_aggregation(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        command_rules={
            "pip-audit": {"exit": 2, "stderr": "dependency service unavailable"},
            "pytest tests/": {"stdout": "1 passed, 1 warning"},
        },
        environment={
            "QUALITY_DOCKER_FIXTURE": json.dumps(
                {"runner_exit": 1, "state": "failed", "manifest_mode": "finding"}
            )
        },
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "dependency service unavailable" in result.stderr
    assert "[FAIL] dependency-audit (exit 2)" in result.stdout
    assert "[FAIL] repository-suite (exit 1)" in result.stdout
    assert "[FAIL] docker-runner (exit 1)" in result.stdout
    assert "[PASS] docker-classifier (exit 0)" in result.stdout
    assert "unapproved Product Findings block the development gate" in result.stderr
    assert _commands_with_executable(commands, "pip-audit")
    assert _commands_with_executable(commands, "pytest")
    assert any("tools/install_sandbox/run.py" in command for command in commands)
    assert result.stdout.rstrip().endswith("complete: FAIL")


def test_complete_gate_runs_independent_checks_after_configuration_preflight_failure(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    (repository / "ruff.install-sandbox.toml").unlink()

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "missing ruff.install-sandbox.toml" in result.stderr
    assert _commands_with_executable(commands, "pip-audit")
    assert any(command[:2] == ("pytest", "tests/") for command in commands)
    assert any("tools/install_sandbox/run.py" in command for command in commands)
    assert "[PASS] dependency-lock" in result.stdout
    assert result.stdout.rstrip().endswith("complete: CONFIGURATION ERROR")


def test_complete_gate_rejects_nonstandard_collected_behavioral_evidence(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    behavioral = repository / "tests/install_sandbox/behavioral"
    behavioral.mkdir(parents=True)
    (behavioral / "behavior_spec.py").write_text(
        "def test_behavior() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    pyproject = repository / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\n[tool.pytest.ini_options]\npython_files = ["*_spec.py"]\n',
        encoding="utf-8",
    )

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Behavioral Evidence is prohibited before Atomic Cutover" in result.stderr
    assert any(
        command[:2] == ("pytest", "tests/install_sandbox/behavioral")
        and "--collect-only" in command
        for command in commands
    )


def test_complete_gate_does_not_invoke_empty_pre_cutover_behavioral_evidence(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    (repository / "tests/install_sandbox/behavioral").mkdir(parents=True)

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[NOT APPLICABLE] behavioral-evidence" in result.stdout
    assert not any(
        command[:2] == ("pytest", "tests/install_sandbox/behavioral") for command in commands
    )


def test_complete_gate_fails_if_a_child_changes_the_dependency_lock(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, _ = run_complete_gate(
        tmp_path,
        repository,
        command_rules={"pip-audit": {"lock_contents": "changed lock\n"}},
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] dependency-lock (exit 1)" in result.stdout
    assert "uv.lock changed during complete gate" in result.stderr


def test_complete_gate_fails_if_a_later_child_restores_the_dependency_lock(
    tmp_path: Path,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, _ = run_complete_gate(
        tmp_path,
        repository,
        command_rules={
            "pip-audit": {"lock_contents": "changed lock\n"},
            "pytest tests/": {"lock_contents": "fixture lock\n"},
        },
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert (repository / "uv.lock").read_text(encoding="utf-8") == "fixture lock\n"
    assert "[FAIL] dependency-lock (exit 1)" in result.stdout
    assert "uv.lock changed during complete gate" in result.stderr


@pytest.mark.parametrize(
    ("docker_scenario", "exit_code", "terminal"),
    [
        (
            {"runner_exit": 124, "state": "incomplete", "manifest_mode": "missing"},
            124,
            "complete: TIMEOUT",
        ),
        (
            {"runner_exit": 2, "run_mode": "missing", "manifest_mode": "missing"},
            2,
            "complete: CONFIGURATION ERROR",
        ),
    ],
)
def test_complete_gate_preserves_approved_aggregate_exits(
    tmp_path: Path,
    docker_scenario: dict[str, object],
    exit_code: int,
    terminal: str,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)

    result, _ = run_complete_gate(
        tmp_path,
        repository,
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps(docker_scenario)},
    )

    assert result.returncode == exit_code, result.stdout + result.stderr
    assert result.stdout.rstrip().endswith(terminal)


@pytest.mark.parametrize(
    ("command_rule", "reported_result"),
    [
        (
            "pytest tests/install_sandbox/unit --collect-only",
            "[FAIL] unit-evidence-collection (exit 5)",
        ),
        ("--cov-fail-under=90", "[FAIL] replacement-coverage (exit 1)"),
    ],
)
def test_complete_gate_blocks_missing_evidence_or_insufficient_branch_coverage(
    tmp_path: Path,
    command_rule: str,
    reported_result: str,
) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")

    result, commands = run_complete_gate(
        tmp_path,
        repository,
        command_rules={command_rule: {"exit": 5 if "collect-only" in command_rule else 1}},
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert reported_result in result.stdout
    assert any("--cov-fail-under=90" in command for command in commands)
    assert _commands_with_executable(commands, "pip-audit")
    assert any("tools/install_sandbox/run.py" in command for command in commands)


def test_complete_gate_rejects_skipped_applicable_coverage_evidence(tmp_path: Path) -> None:
    repository = copy_complete_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")

    result, _ = run_complete_gate(
        tmp_path,
        repository,
        command_rules={"--cov-fail-under=90": {"stdout": "1 passed, 1 skipped"}},
        environment={"QUALITY_DOCKER_FIXTURE": json.dumps({})},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] replacement-coverage (exit 1)" in result.stdout
    assert "required evidence produced a non-passing pytest outcome" in result.stderr
