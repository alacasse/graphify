"""Complete-tier orchestration for the install-sandbox development gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.install_sandbox_quality_checks import CheckResult
from scripts.install_sandbox_quality_complete_checks import run_complete_check_set
from scripts.install_sandbox_quality_complete_environment import inspect_complete_gate_environment
from scripts.install_sandbox_quality_docker import DockerGateRun, run_docker_gate
from scripts.install_sandbox_quality_evidence import FullDockerSelection
from scripts.install_sandbox_quality_state import assess_repository_state


@dataclass(frozen=True)
class CompleteCheckResults:
    checks: tuple[CheckResult, ...]
    docker: DockerGateRun
    lock: CheckResult


def run_complete_checks(repository: Path) -> CompleteCheckResults:
    """Coordinate typed collaborators, then return every independent outcome."""

    environment = inspect_complete_gate_environment(repository)
    state = assess_repository_state(repository)
    checks = (
        environment.configuration,
        *run_complete_check_set(
            state,
            repository,
            environment.dependency_lock.observe,
        ),
    )
    docker = run_docker_gate(
        repository,
        FullDockerSelection(),
        child_completed=environment.dependency_lock.observe,
    )
    environment.dependency_lock.observe()
    return CompleteCheckResults(
        checks=checks,
        docker=docker,
        lock=environment.dependency_lock.result(),
    )
