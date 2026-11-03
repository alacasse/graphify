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
)
from tools.install_sandbox.contracts.effects import EffectSpec
from tools.install_sandbox.contracts.preparation import PreparationResult
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.contracts.timings import Timing, elapsed, measure
from tools.install_sandbox.host.build_context import validate_evidence_location
from tools.install_sandbox.host.campaign_definition import CampaignDefinition
from tools.install_sandbox.host.docker_runtime import (
    ContainerHarness,
    ContainerRunResult,
    SignalCapture,
    WriterObserver,
)
from tools.install_sandbox.host.result_reader import read_evidence
from tools.install_sandbox.host.subject_checkout import captured_subject
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
            raise ValueError("Retained case differs from the submitted effect case")
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
    output_directory: Path | None
    result: CoordinatedResult | None = None
    not_run_reason: str | None = None
    state: Literal["pending", "running", "finished", "not_run", "incomplete"] | None = "pending"
    error: str | None = None
    construction: Literal["constructed", "not_applicable", "unconstructible"] = "constructed"
    construction_reason: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.construction == "constructed":
            if self.output_directory is None or self.state is None:
                raise ValueError("Constructed case requires execution state and evidence path")
            if self.construction_reason is not None:
                raise ValueError("Constructed case cannot have a non-construction reason")
            return
        if self.construction not in {"not_applicable", "unconstructible"}:
            raise ValueError("Invalid case construction classification")
        if not self.construction_reason or not self.construction_reason.strip():
            raise ValueError("Non-constructed case requires a reason")
        if any(
            value is not None
            for value in (
                self.state,
                self.result,
                self.output_directory,
                self.not_run_reason,
                self.error,
            )
        ):
            raise ValueError("Non-constructed case cannot carry execution or evidence")


def _case_entries(cases: list[CampaignCase]) -> dict[str, CampaignCase]:
    entries: dict[str, CampaignCase] = {}
    for entry in cases:
        entry.validate()
        if entry.name in entries:
            raise ValueError("Duplicate campaign case name")
        entries[entry.name] = entry
    return entries


def _cases_passed(cases: list[CampaignCase]) -> bool:
    try:
        entries = _case_entries(cases)
    except ValueError:
        return False
    applicable = [entry for entry in entries.values() if entry.construction != "not_applicable"]
    return bool(applicable) and all(
        entry.construction == "constructed"
        and entry.state == "finished"
        and entry.error is None
        and entry.not_run_reason is None
        and entry.result is not None
        and entry.result.output_directory == entry.output_directory
        and entry.result.passed
        for entry in applicable
    )


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
    prepare_only: bool = False
    preparation_result: PreparationResult | None = None

    @property
    def prepared(self) -> bool:
        return (
            not self.interrupted
            and self.error is None
            and self.preparation_result is not None
            and self.preparation_result.status == "prepared"
            and self.preparation is not None
            and self.preparation.state == "completed"
            and self.preparation.cleanup_complete
            and self.cleanup is not None
            and self.cleanup.state == "completed"
            and self.cleanup.cleanup_complete
        )

    @property
    def successful(self) -> bool:
        return self.prepared if self.prepare_only else self.passed

    @property
    def status(self) -> str:
        if not self.prepare_only:
            return "passed" if self.passed else "incomplete"
        if self.prepared:
            return "prepared"
        if self.preparation_result and self.preparation_result.status == "nonconformant":
            return "nonconformant"
        return "incomplete"

    @property
    def passed(self) -> bool:
        return (
            not self.interrupted
            and self.error is None
            and self.preparation is not None
            and self.preparation.state == "completed"
            and self.preparation.cleanup_complete
            and _cases_passed(self.cases)
            and self.cleanup is not None
            and self.cleanup.state == "completed"
            and self.cleanup.cleanup_complete
        )

    def payload(self) -> dict[str, object]:
        return {
            "version": 3,
            "passed": self.passed,
            "status": self.status,
            **asdict(self, dict_factory=_campaign_fields),
        }

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
        definition: CampaignDefinition,
        output_directory: Path,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300,
        verify_timeout_seconds: float = 60,
        run_timeout_seconds: float = 900,
        graceful_termination_seconds: float = 10,
        interrupts: SignalCapture | None = None,
        observer: WriterObserver | None = None,
        progress: Callable[[CampaignResult], None] | None = None,
        construction_timing: Timing | None = None,
    ) -> CampaignResult:
        """Prepare once, conduct ordered isolated cases, and always finalize owned resources."""
        started = time.monotonic_ns()
        destination = output_directory.expanduser().absolute()
        output = destination.resolve()
        _check_campaign_paths(definition.subject_checkout, destination, output)
        harness = ContainerHarness(
            runtime_executable=runtime_executable,
            build_timeout_seconds=build_timeout_seconds,
            verify_timeout_seconds=verify_timeout_seconds,
            run_timeout_seconds=run_timeout_seconds,
            graceful_termination_seconds=graceful_termination_seconds,
            interrupts=interrupts,
            observer=observer,
        )
        built = definition.built
        materialization = Timing("materialization")
        result = CampaignResult(
            output,
            [CampaignCase(c.name, output / "cases" / c.name) for c in built.cases]
            + [
                CampaignCase(
                    decision.name,
                    None,
                    state=None,
                    construction=decision.classification,
                    construction_reason=decision.reason,
                )
                for decision in built.decisions
            ],
            timings=([construction_timing] if construction_timing is not None else [])
            + [materialization],
            prepare_only=definition.prepare_only,
        )
        # Keep skill repairs after Markdown cases and their construction decisions.
        repair_order = {"missing-reference": 1, "altered-reference": 2, "altered-skill": 3}
        result.cases.sort(key=lambda entry: repair_order.get(entry.name, 0))
        with harness:
            try:
                self._execute_campaign(harness, definition, result, materialization, progress)
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

    def _execute_campaign(
        self,
        harness: ContainerHarness,
        definition: CampaignDefinition,
        result: CampaignResult,
        materialization: Timing,
        progress: Callable[[CampaignResult], None] | None,
    ) -> None:
        with measure(materialization):
            self._materialize(definition, result.output_directory)
        _save_progress(result, progress)
        self._prepare_image(
            harness, definition.subject_checkout, definition.effects, definition.context, result
        )
        assert result.preparation is not None
        result.timings.extend(result.preparation.timings)
        _save_progress(result, progress)
        if not definition.prepare_only:
            self._conduct_cases(harness, list(definition.built.cases), result, progress)

    @staticmethod
    def _prepare_image(
        harness: ContainerHarness,
        subject: Path,
        effects: EffectSpec,
        context: SubjectContext,
        result: CampaignResult,
    ) -> None:
        with captured_subject(subject, context) as captured:
            if context.package_root is None:
                result.preparation = harness.prepare(
                    captured, result.output_directory / "preparation"
                )
            else:
                result.preparation = harness.prepare(
                    captured,
                    result.output_directory / "preparation",
                    effects=effects,
                    subject_context=context,
                )
                result.preparation_result = harness.preparation_result

    @staticmethod
    def _materialize(definition: CampaignDefinition, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "inputs").mkdir()
        if definition.built.cases:
            (output / "cases").mkdir()
        for case, transport in zip(definition.built.cases, definition.transports, strict=True):
            (output / "cases" / case.name).mkdir()
            (output / "inputs" / f"{case.name}.json").write_text(
                transport, encoding="utf-8", newline="\n"
            )

    def _conduct_cases(
        self,
        harness: ContainerHarness,
        cases: list[EffectInstallCase],
        result: CampaignResult,
        progress: Callable[[CampaignResult], None] | None,
    ) -> None:
        assert result.preparation is not None
        entries = _associate_cases(cases, result.cases)
        if result.preparation.state != "completed" or not result.preparation.cleanup_complete:
            self._skip_remaining(
                result, "Common preparation unavailable: " + result.preparation.detail
            )
            _save_progress(result, progress)
            return
        for case in cases:
            entry = entries[case.name]
            assert entry.output_directory is not None
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
            if entry.construction != "constructed":
                continue
            if entry.state == "running":
                entry.state, entry.error = "incomplete", reason
            elif entry.result is None and entry.state != "not_run":
                entry.state, entry.not_run_reason = "not_run", reason


def _associate_cases(
    cases: list[EffectInstallCase], entries: list[CampaignCase]
) -> dict[str, CampaignCase]:
    indexed = _case_entries(entries)
    names = [case.name for case in cases]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate constructed case name")
    constructed = {name for name, entry in indexed.items() if entry.construction == "constructed"}
    if constructed != set(names):
        raise ValueError("Constructed campaign entries do not match the supplied cases")
    return indexed


def _check_campaign_paths(subject: Path, destination: Path, output: Path) -> None:
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    validate_evidence_location(subject, output)
    if any(p.is_symlink() for p in (destination, *destination.parents)) or "," in str(output):
        raise ValueError("Campaign evidence must not be a symlink or contain commas")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Campaign evidence directory must be fresh or empty")


def _save_progress(
    result: CampaignResult, progress: Callable[[CampaignResult], None] | None
) -> None:
    result.save()
    if progress is not None:
        progress(result)
