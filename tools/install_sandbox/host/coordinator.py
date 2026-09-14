"""Assemble and conduct a selected project case from discovered target facts."""

import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal, cast

import yaml

from tools.install_sandbox.contracts.case import (
    CASE_NAMES,
    InstallTestCase,
    case_operations,
    first_install_files,
)
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.contracts.spec import InstallTestSpec, fields, text
from tools.install_sandbox.contracts.timings import Timing, elapsed, measure
from tools.install_sandbox.host.docker_runtime import ContainerHarness, ContainerRunResult
from tools.install_sandbox.host.result_reader import read_result
from tools.install_sandbox.host.spec_reader import InstallSpecReader
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
    container: ContainerRunResult, case: InstallTestCase, output: Path
) -> CoordinatedResult:
    try:
        result = read_result(output, case)
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
    selection_origin: Literal["default", "explicit"] = "explicit"
    selected_cases: list[str] = field(default_factory=list[str])
    not_selected_cases: list[str] = field(default_factory=list[str])
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

    def save(self) -> None:
        from tools.install_sandbox.host.timing_report import render_campaign

        payload = {
            "version": 1,
            "passed": self.passed,
            **asdict(self, dict_factory=_campaign_fields),
        }
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
        specs_directory: Path,
        target: str,
        case_names: Sequence[str] | None = None,
        subject_checkout: Path,
        output_directory: Path,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300,
        verify_timeout_seconds: float = 60,
        run_timeout_seconds: float = 900,
        graceful_termination_seconds: float = 10,
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
            )
            names = self._select_cases(case_names)
            subject, output, cases = self._prepare_campaign(
                specs_directory,
                target,
                names,
                subject_checkout,
                output_directory,
            )
        result = CampaignResult(
            output,
            [CampaignCase(c.name, output / "cases" / c.name) for c in cases],
            selection_origin="default" if case_names is None else "explicit",
            selected_cases=names,
            not_selected_cases=[name for name in CASE_NAMES if name not in names],
            timings=[inputs],
        )
        with harness:
            try:
                result.save()
                result.preparation = harness.prepare(subject, output / "preparation")
                result.timings.extend(result.preparation.timings)
                result.save()
                self._conduct_cases(harness, cases, result)
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
                    result.save()
                except EvidenceWriteError as error:
                    result.error = f"{result.error or 'Campaign evidence incomplete'}; {error}"
        return result

    @staticmethod
    def _select_cases(names: Sequence[str] | None) -> list[str]:
        if names is None:
            path = Path(__file__).with_name("campaign-defaults.yaml")
            try:
                data = fields(yaml.safe_load(path.read_text(encoding="utf-8")), "default_cases")
                configured = data["default_cases"]
                if not isinstance(configured, list):
                    raise ValueError("default_cases must be an ordered list")
                names = [text(item) for item in cast(list[object], configured)]
            except (OSError, ValueError, yaml.YAMLError) as error:
                raise ValueError(f"Cannot load campaign defaults {path}: {error}") from error
        if isinstance(names, str) or not names:
            raise ValueError("Select a nonempty ordered list of case names")
        if len(set(names)) != len(names):
            raise ValueError("Duplicate case names are not allowed")
        for name in names:
            case_operations(name)
        return list(names)

    def _prepare_campaign(
        self,
        specs: Path,
        target: str,
        names: Sequence[str],
        subject: Path,
        output: Path,
    ) -> tuple[Path, Path, list[InstallTestCase]]:
        subject = subject.expanduser().resolve(strict=True)
        destination = output.expanduser()
        output = destination.resolve()
        _check_campaign_paths(subject, destination, output)
        catalog = InstallSpecReader().read(specs)
        if target not in catalog:
            raise ValueError(f"Target not found in {specs}: {target}")
        cases = [self.build_case(target, catalog[target], case_name=name) for name in names]
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
        cases: list[InstallTestCase],
        result: CampaignResult,
    ) -> None:
        assert result.preparation is not None
        if result.preparation.state != "completed" or not result.preparation.cleanup_complete:
            self._skip_remaining(
                result, "Common preparation unavailable: " + result.preparation.detail
            )
            result.save()
            return
        for case, entry in zip(cases, result.cases, strict=True):
            if harness.interrupted:
                self._skip_remaining(result, "Campaign interrupted")
                break
            entry.state = "running"
            result.save()
            entry.result = self._run_and_read(harness, case, entry.output_directory, result)
            entry.state = "finished"
            result.save()
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
        result.save()

    def _run_and_read(
        self,
        harness: ContainerHarness,
        case: InstallTestCase,
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

    def write_case(
        self,
        specs_directory: Path,
        target: str,
        case_file: Path,
        *,
        case_name: str = "first-install",
    ) -> InstallTestCase:
        """Discover targets, assemble one project case and write its complete JSON."""
        specs = InstallSpecReader().read(specs_directory)
        if target not in specs:
            raise ValueError(f"Target not found in {specs_directory}: {target}")
        case = self.build_case(target, specs[target], case_name=case_name)
        case.write(case_file)
        return case

    def build_case(
        self, target: str, spec: InstallTestSpec, *, case_name: str = "first-install"
    ) -> InstallTestCase:
        if "project" not in spec.scopes:
            raise ValueError("Installation case requires a supported project scope")
        return InstallTestCase(
            name=case_name,
            target=target,
            scope="project",
            spec=spec,
            initial_files=first_install_files(spec, case_name),
            operations=case_operations(case_name),
        )


def _check_campaign_paths(subject: Path, destination: Path, output: Path) -> None:
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    if subject.is_relative_to(output) or output.is_relative_to(subject):
        raise ValueError("Subject and campaign evidence directories must be separate")
    if destination.is_symlink() or "," in str(output):
        raise ValueError("Campaign evidence must not be a symlink or contain commas")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Campaign evidence directory must be fresh or empty")
