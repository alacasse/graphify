"""Conduct the native two-step reinstall from effects and explicit subject context."""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    SubjectContext,
    build_reinstall_case,
    unique_object,
)
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.contracts.timings import Timing, elapsed, measure
from tools.install_sandbox.host.build_context import validate_evidence_location
from tools.install_sandbox.host.docker_runtime import (
    ContainerHarness,
    ContainerRunResult,
    SignalCapture,
    WriterObserver,
)
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence
from tools.install_sandbox.host.timing_reader import CaseTimingResult, read_timings


@dataclass(frozen=True)
class CoordinatedResult:
    """Keep container execution, the validated case and transport diagnostics separate."""

    container: ContainerRunResult
    test: InstallTestResult | None
    result_error: str | None
    output_directory: Path
    duration_seconds: float | None = None
    timings: list[Timing] = field(default_factory=list[Timing])
    container_timings: CaseTimingResult = field(default_factory=CaseTimingResult)

    @property
    def passed(self) -> bool:
        return (
            self.test is not None
            and self.test.status == "passed"
            and self.result_error is None
            and self.container.state == "completed"
            and self.container.cleanup_complete
        )


def _collect_result(
    container: ContainerRunResult, case: EffectInstallCase, output: Path
) -> CoordinatedResult:
    try:
        result = read_evidence(output)
        retained = EffectInstallCase.from_json((output / "case.json").read_text(encoding="utf-8"))
        if retained != case:
            raise ValueError("Retained case differs from the submitted reinstall case")
    except FileNotFoundError as error:
        return CoordinatedResult(container, None, f"Result unavailable: {error}", output)
    except OSError as error:
        return CoordinatedResult(container, None, f"Result unreadable: {error}", output)
    except (ValueError, RecursionError, OverflowError) as error:
        return CoordinatedResult(container, None, f"Result invalid: {error}", output)
    return CoordinatedResult(container, result, None, output)


@dataclass
class CampaignCase:
    name: str
    output_directory: Path
    result: CoordinatedResult | None = None
    not_run_reason: str | None = None
    state: Literal["pending", "running", "finished", "not_run", "incomplete"] = "pending"
    error: str | None = None


@dataclass
class CampaignResult:
    output_directory: Path
    cases: list[CampaignCase]
    interrupted: bool = False
    preparation: ContainerRunResult | None = None
    cleanup: ContainerRunResult | None = None
    error: str | None = None
    duration_seconds: float | None = None
    timings: list[Timing] = field(default_factory=list[Timing])

    @property
    def passed(self) -> bool:
        return (
            not self.interrupted
            and self.error is None
            and self.preparation is not None
            and self.preparation.state == "completed"
            and self.preparation.cleanup_complete
            and bool(self.cases)
            and all(c.result is not None and c.result.passed for c in self.cases)
            and self.cleanup is not None
            and self.cleanup.state == "completed"
            and self.cleanup.cleanup_complete
        )

    def payload(self) -> dict[str, object]:
        return {"version": 2, "passed": self.passed, **asdict(self, dict_factory=_campaign_fields)}

    def save(self) -> None:
        from tools.install_sandbox.host.timing_report import render_campaign

        payload = self.payload()
        documents = {
            "campaign.json": json.dumps(payload, indent=2, default=str) + "\n",
            "campaign.txt": render_campaign(self),
        }
        try:
            for name, content in documents.items():
                temporary = self.output_directory / f"{name}.tmp"
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(self.output_directory / name)
        except OSError as error:
            raise EvidenceWriteError(f"Cannot save campaign evidence: {error}") from error


def _campaign_fields(fields: list[tuple[str, object]]) -> dict[str, object]:
    return {
        key: value for key, value in fields if key != "dependency_preparation" or value is not None
    }


class InstallTestCoordinator:
    def run_campaign(
        self,
        *,
        spec_file: Path,
        subject_context_file: Path,
        subject_checkout: Path,
        output_directory: Path,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300,
        verify_timeout_seconds: float = 60,
        run_timeout_seconds: float = 900,
        graceful_termination_seconds: float = 10,
        interrupts: SignalCapture | None = None,
        observer: WriterObserver | None = None,
        progress: Callable[[CampaignResult], None] | None = None,
    ) -> CampaignResult:
        """Prepare once, conduct ordered isolated cases, and always finalize owned resources."""
        started = time.monotonic_ns()
        inputs = Timing("inputs")
        with measure(inputs):
            harness = ContainerHarness(
                runtime_executable=runtime_executable,
                build_timeout_seconds=build_timeout_seconds,
                verify_timeout_seconds=verify_timeout_seconds,
                run_timeout_seconds=run_timeout_seconds,
                graceful_termination_seconds=graceful_termination_seconds,
                interrupts=interrupts,
                observer=observer,
            )
            subject, output, cases = self._prepare_campaign(
                spec_file,
                subject_context_file,
                subject_checkout,
                output_directory,
            )
        result = CampaignResult(
            output,
            [CampaignCase(c.name, output / "cases" / c.name) for c in cases],
            timings=[inputs],
        )
        with harness:
            try:
                _save_progress(result, progress)
                result.preparation = harness.prepare(subject, output / "preparation")
                result.timings.extend(result.preparation.timings)
                _save_progress(result, progress)
                self._conduct_cases(harness, cases, result, progress)
            except (Exception, KeyboardInterrupt) as error:
                result.interrupted = isinstance(error, KeyboardInterrupt)
                result.error = f"Campaign stopped: {type(error).__name__}: {error}"
                self._skip_remaining(result, result.error)
            finally:
                result.cleanup = harness.cleanup()
                result.interrupted = result.interrupted or harness.interrupted
                result.timings.extend(result.cleanup.timings)
                result.duration_seconds = elapsed(started)
                try:
                    _save_progress(result, progress)
                except EvidenceWriteError as error:
                    result.error = f"{result.error or 'Campaign evidence incomplete'}; {error}"
        return result

    def _prepare_campaign(
        self,
        spec: Path,
        context: Path,
        subject: Path,
        output: Path,
    ) -> tuple[Path, Path, list[EffectInstallCase]]:
        subject = subject.expanduser().resolve(strict=True)
        destination = output.expanduser()
        output = destination.resolve()
        _check_campaign_paths(subject, destination, output)
        effects = EffectSpecReader().read(spec)
        subject_context = SubjectContext.from_data(
            json.loads(context.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        )
        cases = [build_reinstall_case(effects, subject_context, subject_context.identity)]
        output.mkdir(parents=True, exist_ok=True)
        (output / "inputs").mkdir()
        (output / "cases").mkdir()
        for case in cases:
            (output / "cases" / case.name).mkdir()
            case.write(output / "inputs" / f"{case.name}.json")
        return subject, output, cases

    def _conduct_cases(
        self,
        harness: ContainerHarness,
        cases: list[EffectInstallCase],
        result: CampaignResult,
        progress: Callable[[CampaignResult], None] | None,
    ) -> None:
        assert result.preparation is not None
        if result.preparation.state != "completed" or not result.preparation.cleanup_complete:
            self._skip_remaining(
                result, "Common preparation unavailable: " + result.preparation.detail
            )
            _save_progress(result, progress)
            return
        for case, entry in zip(cases, result.cases, strict=True):
            if harness.interrupted:
                self._skip_remaining(result, "Campaign interrupted")
                break
            entry.state = "running"
            _save_progress(result, progress)
            entry.result = self._run_and_read(harness, case, entry.output_directory, result)
            entry.state = "finished"
            _save_progress(result, progress)
            if (
                not entry.result.container.cleanup_complete
                or harness.interrupted
                or entry.result.container.state == "interrupted"
            ):
                self._skip_remaining(
                    result,
                    "Previous container cleanup incomplete"
                    if not entry.result.container.cleanup_complete
                    else "Campaign interrupted",
                )
                break
        _save_progress(result, progress)

    def _run_and_read(
        self,
        harness: ContainerHarness,
        case: EffectInstallCase,
        output: Path,
        campaign: CampaignResult,
    ) -> CoordinatedResult:
        started = time.monotonic_ns()
        container = harness.run_case(
            case_file=campaign.output_directory / "inputs" / f"{case.name}.json",
            output_directory=output,
        )
        reading = Timing("read")
        with measure(reading):
            result = _collect_result(container, case, output)
            internal = read_timings(output, case)
        return replace(
            result,
            duration_seconds=elapsed(started),
            timings=[*container.timings, reading],
            container_timings=internal,
        )

    @staticmethod
    def _skip_remaining(result: CampaignResult, reason: str) -> None:
        for entry in result.cases:
            if entry.state == "running":
                entry.state, entry.error = "incomplete", reason
            elif entry.result is None:
                entry.state, entry.not_run_reason = "not_run", reason


def _check_campaign_paths(subject: Path, destination: Path, output: Path) -> None:
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    validate_evidence_location(subject, output)
    if destination.is_symlink() or "," in str(output):
        raise ValueError("Campaign evidence must not be a symlink or contain commas")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Campaign evidence directory must be fresh or empty")


def _save_progress(
    result: CampaignResult, progress: Callable[[CampaignResult], None] | None
) -> None:
    result.save()
    if progress is not None:
        progress(result)
