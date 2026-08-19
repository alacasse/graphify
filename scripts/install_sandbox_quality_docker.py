"""Run and classify official Docker evidence without creating another authority."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    FROZEN_PYTHON_RUN,
    CheckResult,
    CheckStatus,
)
from install_sandbox_quality_evidence import (
    RUN_RECORD,
    DockerSelection,
    FailedEvidence,
    IncompleteEvidence,
    InterruptedEvidence,
    PassedEvidence,
    TerminalEvidence,
    consume_terminal_evidence,
)
from install_sandbox_quality_manifest import ProductFinding
from install_sandbox_quality_state import (
    GatePhase,
    RepositoryStateFailure,
    assess_repository_state,
)

RUNNER = "tools/install_sandbox/run.py"
CLASSIFIER_MODULE = "tools.install_sandbox.ci_result"


@dataclass(frozen=True)
class LegacyFindingException:
    finding: ProductFinding
    approved_in: str
    expires_on: date

    def __post_init__(self) -> None:
        if not self.approved_in.strip():
            raise ValueError("legacy finding approval requires a durable reference")


# The accepted baseline records every legacy finding as unclear and explicitly
# pre-approves none. Any future entry requires its exact evidence digest, durable
# approval reference, and expiry instead of widening this policy by family/name.
APPROVED_LEGACY_FINDINGS: tuple[LegacyFindingException, ...] = ()


@dataclass(frozen=True)
class DockerGateContext:
    bundle: Path
    results: tuple[CheckResult, ...]


@dataclass(frozen=True)
class DockerPassed:
    context: DockerGateContext
    advisory_findings: tuple[ProductFinding, ...] = ()


@dataclass(frozen=True)
class DockerFailed:
    context: DockerGateContext
    reason: str


@dataclass(frozen=True)
class DockerTimedOut:
    context: DockerGateContext


@dataclass(frozen=True)
class DockerConfigurationError:
    context: DockerGateContext


type DockerGateRun = DockerPassed | DockerFailed | DockerTimedOut | DockerConfigurationError


def _run_child(name: str, command: Sequence[str], repository: Path) -> CheckResult:
    try:
        completed = subprocess.run(
            command,
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CheckResult(
            name=name,
            status=CheckStatus.FAIL,
            exit_code=CONFIGURATION_EXIT,
            stdout="",
            stderr=f"unable to start child command: {error}\n",
            configuration_error=True,
        )
    return CheckResult(
        name=name,
        status=CheckStatus.PASS if completed.returncode == 0 else CheckStatus.FAIL,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _runner_command(
    repository: Path,
    bundle: Path,
    selection: DockerSelection,
) -> tuple[str, ...]:
    return (
        *FROZEN_PYTHON_RUN,
        "python",
        RUNNER,
        "--repo",
        str(repository),
        *selection.runner_arguments(),
        "--scope",
        "both",
        "--output",
        str(bundle),
    )


def _classifier_command(bundle: Path, runner_exit: int) -> tuple[str, ...]:
    return (
        *FROZEN_PYTHON_RUN,
        "python",
        "-m",
        CLASSIFIER_MODULE,
        "--run-json",
        str(bundle / RUN_RECORD),
        "--runner-exit-code",
        str(runner_exit),
    )


def approved_advisory_findings(
    phase: GatePhase | None,
    findings: tuple[ProductFinding, ...],
    exceptions: tuple[LegacyFindingException, ...],
    on_date: date,
) -> tuple[ProductFinding, ...]:
    """Return only an exact, current, construction-phase advisory set."""

    if phase is not GatePhase.REPLACEMENT_CONSTRUCTION:
        return ()
    approved = {item.finding: item for item in exceptions if item.expires_on >= on_date}
    return findings if findings and all(finding in approved for finding in findings) else ()


def _repository_phase(repository: Path) -> GatePhase | None:
    state = assess_repository_state(repository)
    return None if isinstance(state, RepositoryStateFailure) else state.phase


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _has_configuration_failure(
    context: DockerGateContext,
    runner: CheckResult,
    classifier: CheckResult,
    runner_exit: int,
) -> bool:
    return (
        runner.configuration_error
        or classifier.configuration_error
        or (runner_exit == CONFIGURATION_EXIT and not (context.bundle / RUN_RECORD).exists())
    )


def _classify_terminal_evidence(
    repository: Path,
    context: DockerGateContext,
    evidence: TerminalEvidence,
    on_date: date,
) -> DockerGateRun:
    if isinstance(evidence, PassedEvidence):
        return DockerPassed(context)
    if isinstance(evidence, FailedEvidence):
        advisory = approved_advisory_findings(
            _repository_phase(repository),
            evidence.findings,
            APPROVED_LEGACY_FINDINGS,
            on_date,
        )
        if advisory:
            return DockerPassed(context, advisory_findings=advisory)
        return DockerFailed(context, "unapproved Product Findings block the development gate")
    outcome = "incomplete" if isinstance(evidence, IncompleteEvidence) else "interrupted"
    assert isinstance(evidence, (IncompleteEvidence, InterruptedEvidence))
    return DockerFailed(context, f"{outcome} Run Outcome blocks the development gate")


def _classify_gate_run(
    repository: Path,
    context: DockerGateContext,
    runner: CheckResult,
    classifier: CheckResult,
    runner_exit: int,
    evidence: TerminalEvidence | None,
    diagnostic_error: str | None,
    on_date: date,
) -> DockerGateRun:
    if _has_configuration_failure(context, runner, classifier, runner_exit):
        return DockerConfigurationError(context)
    if runner_exit == 124:
        return DockerTimedOut(context)
    if diagnostic_error is not None:
        return DockerFailed(context, f"Diagnostic Bundle is invalid: {diagnostic_error}")
    if classifier.exit_code != 0:
        return DockerFailed(context, "diagnostic classification or publication failed")
    if evidence is None:
        return DockerFailed(context, "Diagnostic Bundle evidence is unavailable")
    return _classify_terminal_evidence(repository, context, evidence, on_date)


def run_docker_gate(
    repository: Path,
    selection: DockerSelection,
    *,
    clock: Callable[[], date] = _utc_today,
) -> DockerGateRun:
    """Run the supported host and classifier interfaces, then apply gate policy."""

    bundle = Path(tempfile.mkdtemp(prefix="graphify-install-sandbox-quality-"))
    runner = _run_child(
        "docker-runner",
        _runner_command(repository, bundle, selection),
        repository,
    )
    runner_exit = runner.exit_code if runner.exit_code is not None else CONFIGURATION_EXIT
    classifier = _run_child(
        "docker-classifier",
        _classifier_command(bundle, runner_exit),
        repository,
    )
    context = DockerGateContext(bundle=bundle, results=(runner, classifier))
    evidence: TerminalEvidence | None = None
    diagnostic_error: str | None = None
    try:
        evidence = consume_terminal_evidence(repository, bundle, selection, runner_exit)
    except ValueError as error:
        diagnostic_error = str(error)
    return _classify_gate_run(
        repository,
        context,
        runner,
        classifier,
        runner_exit,
        evidence,
        diagnostic_error,
        clock(),
    )
