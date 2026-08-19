from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.quality_gate_support import copy_docker_gate_fixture, run_quality_gate


@dataclass(frozen=True)
class DockerFixtureScenario:
    runner_exit: int = 0
    state: str = "passed"
    run_mode: str = "valid"
    manifest_mode: str = "valid"
    classifier_exit: int = 0
    classifier_message: str = "::notice::diagnostic passed"
    recorded_exit: int | None = None


DEFAULT_DOCKER_FIXTURE = DockerFixtureScenario()


def _run_docker_gate(
    tmp_path: Path,
    *,
    arguments: tuple[str, ...] = ("docker", "--target", "fixture"),
    scenario: DockerFixtureScenario = DEFAULT_DOCKER_FIXTURE,
):
    repository = copy_docker_gate_fixture(tmp_path)
    environment = {
        "QUALITY_DOCKER_FIXTURE": json.dumps(
            {
                "runner_exit": scenario.runner_exit,
                "state": scenario.state,
                "run_mode": scenario.run_mode,
                "manifest_mode": scenario.manifest_mode,
                "recorded_exit": (
                    scenario.recorded_exit
                    if scenario.recorded_exit is not None
                    else scenario.runner_exit
                ),
            }
        ),
        "QUALITY_CLASSIFIER_EXIT": str(scenario.classifier_exit),
        "QUALITY_CLASSIFIER_MESSAGE": scenario.classifier_message,
    }
    return run_quality_gate(repository, arguments=arguments, environment=environment)


@pytest.mark.parametrize(
    ("arguments", "selection"),
    [
        (("docker", "--target", "fixture"), "target=fixture all=False scope=both"),
        (("docker", "--all"), "target=None all=True scope=both"),
    ],
)
@pytest.mark.install_sandbox_proof("docker-selection-positive")
def test_docker_gate_uses_approved_targeted_and_full_selection(
    tmp_path: Path,
    arguments: tuple[str, ...],
    selection: str,
) -> None:
    result = _run_docker_gate(tmp_path, arguments=arguments)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"runner raw: {selection} exit=0" in result.stdout
    assert "::notice::diagnostic passed" in result.stdout
    assert "[PASS] docker-runner (exit 0)" in result.stdout
    assert "[PASS] docker-classifier (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("docker: PASS")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("docker",), "one of the arguments --target --all is required"),
        (("docker", "--target", "fixture", "--all"), "not allowed with argument"),
        (("docker", "--target", ""), "Docker target must not be empty"),
    ],
)
def test_docker_gate_rejects_invalid_selection_usage(
    tmp_path: Path,
    arguments: tuple[str, ...],
    message: str,
) -> None:
    result = _run_docker_gate(tmp_path, arguments=arguments)

    assert result.returncode == 2
    assert message in result.stderr


@pytest.mark.install_sandbox_proof("docker-finding-propagation")
def test_docker_gate_preserves_raw_findings_but_blocks_unapproved_findings(
    tmp_path: Path,
) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            runner_exit=1,
            state="failed",
            manifest_mode="finding",
            classifier_message="::warning::diagnostic contains Product Findings",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "runner raw: target=fixture all=False scope=both exit=1" in result.stdout
    assert "::warning::diagnostic contains Product Findings" in result.stdout
    assert "[FAIL] docker-runner (exit 1)" in result.stdout
    assert "unapproved Product Findings block the development gate" in result.stderr
    assert result.stdout.rstrip().endswith("docker: FAIL")


@pytest.mark.parametrize(
    ("runner_exit", "state"),
    [
        (2, "incomplete"),
        (143, "interrupted"),
    ],
)
def test_docker_gate_blocks_incomplete_and_interrupted_results(
    tmp_path: Path,
    runner_exit: int,
    state: str,
) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            runner_exit=runner_exit,
            state=state,
            manifest_mode="missing",
            classifier_exit=runner_exit,
            classifier_message=f"::error::diagnostic {state}",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert f"[FAIL] docker-runner (exit {runner_exit})" in result.stdout
    assert f"::error::diagnostic {state}" in result.stdout
    assert result.stdout.rstrip().endswith("docker: FAIL")


@pytest.mark.install_sandbox_proof("docker-timeout")
def test_docker_gate_preserves_the_approved_timeout_exit(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            runner_exit=124,
            state="incomplete",
            manifest_mode="missing",
            classifier_exit=124,
            classifier_message="::error::diagnostic incomplete",
        ),
    )

    assert result.returncode == 124, result.stdout + result.stderr
    assert "[FAIL] docker-runner (exit 124)" in result.stdout
    assert "[FAIL] docker-classifier (exit 124)" in result.stdout
    assert result.stdout.rstrip().endswith("docker: TIMEOUT")


@pytest.mark.parametrize("manifest_mode", ["missing", "malformed", "mismatch", "incomplete"])
def test_docker_gate_rejects_malformed_or_incoherent_manifest(
    tmp_path: Path,
    manifest_mode: str,
) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(manifest_mode=manifest_mode),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Diagnostic Bundle is invalid" in result.stderr
    assert "[PASS] docker-runner (exit 0)" in result.stdout
    assert "[PASS] docker-classifier (exit 0)" in result.stdout
    assert result.stdout.rstrip().endswith("docker: FAIL")


def test_docker_gate_rejects_malformed_run_record(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            run_mode="malformed",
            classifier_exit=2,
            classifier_message="::error::invalid run record",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Diagnostic Bundle is invalid" in result.stderr
    assert "::error::invalid run record" in result.stdout
    assert "[FAIL] docker-classifier (exit 2)" in result.stdout


def test_docker_gate_rejects_incomplete_run_record(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            run_mode="incomplete",
            classifier_exit=2,
            classifier_message="::error::incomplete run record",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Run Record phase is missing" in result.stderr
    assert "::error::incomplete run record" in result.stdout


def test_docker_gate_rejects_recorded_and_observed_exit_mismatch(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            recorded_exit=1,
            classifier_exit=2,
            classifier_message="::error::runner exit mismatch",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Run Record exit does not match the observed runner exit" in result.stderr
    assert "::error::runner exit mismatch" in result.stdout
    assert "[FAIL] docker-classifier (exit 2)" in result.stdout


@pytest.mark.install_sandbox_proof("docker-classifier-publication-failure")
def test_docker_gate_blocks_classifier_or_publication_failure(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(
            classifier_exit=1,
            classifier_message="::error::artifact publication failed",
        ),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::artifact publication failed" in result.stdout
    assert "[FAIL] docker-classifier (exit 1)" in result.stdout
    assert result.stdout.rstrip().endswith("docker: FAIL")


@pytest.mark.install_sandbox_proof("docker-configuration-exit")
def test_docker_gate_distinguishes_runner_usage_failure(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        arguments=("docker", "--target", "unknown"),
        scenario=DockerFixtureScenario(
            runner_exit=2,
            state="incomplete",
            run_mode="missing",
            manifest_mode="missing",
            classifier_exit=2,
            classifier_message="::error::invalid run record",
        ),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid choice: 'unknown'" in result.stderr
    assert "[FAIL] docker-runner (exit 2)" in result.stdout
    assert "[FAIL] docker-classifier (exit 2)" in result.stdout
    assert result.stdout.rstrip().endswith("docker: CONFIGURATION ERROR")


def test_docker_gate_rejects_passed_record_with_finding_manifest(tmp_path: Path) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(manifest_mode="finding"),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "passed Run Outcome disagrees with Product Findings" in result.stderr
    assert result.stdout.rstrip().endswith("docker: FAIL")


@pytest.mark.parametrize(
    ("manifest_mode", "message"),
    [
        ("partial_coverage", "requested catalog scope"),
        ("bad_phase_command", "contains a failed command"),
        ("bad_purge_command", "passing purge contains failed observations"),
        ("na_command", "not-applicable phase"),
        ("unsupported_scope", "disagrees with YAML scope support"),
    ],
)
def test_docker_gate_rejects_incomplete_or_contradictory_raw_evidence(
    tmp_path: Path,
    manifest_mode: str,
    message: str,
) -> None:
    result = _run_docker_gate(
        tmp_path,
        scenario=DockerFixtureScenario(manifest_mode=manifest_mode),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stderr
    assert result.stdout.rstrip().endswith("docker: FAIL")
