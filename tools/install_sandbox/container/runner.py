"""Execute native reinstall phases against expectations retained before commands."""

import time
from pathlib import Path

from tools.install_sandbox.container.case_publication import CasePublisher
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.intermediate_execution import conduct_intermediate
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.initial_preparation import REFERENCES
from tools.install_sandbox.contracts.observation import FilesystemSnapshot, same_observation
from tools.install_sandbox.contracts.results import (
    EvidenceWriteError,
    InstallTestResult,
    StepState,
)
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)
from tools.install_sandbox.rules.initial_preparation import InitialPreparationLifecycle
from tools.install_sandbox.rules.step_lifecycle import (
    CommandRetained,
    CommandReturned,
    ExpectationsRetained,
    ObservationRetained,
    PreparationObserved,
    Prepared,
    StopStep,
    Terminate,
    VerificationComputed,
    VerificationRetained,
    advance,
    start,
    status,
)


def _check_directories(subject: Path, case_file: Path, work: Path, output: Path) -> None:
    for left, right in ((subject, work), (subject, output), (work, output)):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("Subject, work and evidence directories must be separate")
    if case_file.is_relative_to(work) or case_file.is_relative_to(output):
        raise ValueError("Case file must be outside work and evidence directories")
    for path in (work, output):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError(f"Directory must be fresh or empty: {path}")


class InstallTestRunner:
    def __init__(self, driver: InstallerDriver | None = None):
        self.driver = driver if driver is not None else InstallerDriver()
        self.verifier = EffectVerifier()

    def run_case(
        self,
        *,
        reference_sources: Path,
        prepared_executable: Path,
        case_file: Path,
        work_directory: Path,
        output_directory: Path,
    ) -> InstallTestResult:
        started = time.monotonic_ns()
        subject, case_path, work, output = (
            p.resolve() for p in (reference_sources, case_file, work_directory, output_directory)
        )
        case = EffectInstallCase.from_json(case_path.read_text(encoding="utf-8"))
        _check_directories(subject, case_path, work, output)
        writer = TestResultWriter(output)
        case.write(output / "case.json")
        writer.write_metadata("evidence-format.json", {"format": "explicit-expectations-v7"})
        writer.initialize_timings(case.name, len(case.operations))
        publisher = CasePublisher(case, writer)
        lifecycle = InitialPreparationLifecycle()
        try:
            publisher.publish_initial(lifecycle)
            writer.append_log("journal.log", "Validated native case; starting preparation\n")
            writer.append_log("preparation.log", "Package availability inherited from campaign\n")
            self._run(case, subject, prepared_executable, work, writer, publisher, lifecycle)
        except BaseException:
            writer.halted = True
            raise
        finally:
            # Timings never authorize progression or overwrite the last result.
            writer.finish_timings(started)
        return publisher.result

    def _run(
        self,
        case: EffectInstallCase,
        subject: Path,
        executable: Path,
        work: Path,
        writer: TestResultWriter,
        publisher: CasePublisher,
        lifecycle: InitialPreparationLifecycle,
    ) -> None:
        operations = _InitialOperations(case, subject, work, writer, lifecycle, self.verifier)
        with writer.measure("initial"):
            while (operation := lifecycle.next_operation()) is not None:
                try:
                    operations.execute(operation)
                except EvidenceWriteError:
                    raise
                except (OSError, ValueError) as error:
                    lifecycle.stop(
                        operation,
                        "validation" if isinstance(error, ValueError) else "io",
                        str(error) or type(error).__name__,
                    )
                    writer.write_metadata(
                        REFERENCES["failure"], lifecycle.failure_candidate().to_data()
                    )
                    lifecycle.retain_failure(REFERENCES["failure"])
                # Failed publication cannot become an operational diagnostic or a retry.
                publisher.publish_initial(lifecycle)
        if publisher.decision.segment != "installation":
            return
        assert operations.environment is not None and operations.sources is not None
        assert operations.expectations is not None and operations.before is not None
        self._steps(
            case,
            executable,
            operations.environment,
            operations.sources,
            operations.expectations,
            operations.before,
            writer,
            publisher,
        )

    def _steps(
        self,
        case: EffectInstallCase,
        executable: Path,
        environment: EffectEnvironment,
        sources: FilesystemSnapshot,
        expectations: ExpectationSet,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        publisher: CasePublisher,
    ) -> None:
        while True:
            segment = publisher.decision.segment
            if segment == "repair":
                transition = conduct_intermediate(
                    case, sources, expectations, before, environment, writer, publisher
                )
                if transition is None:
                    return
                expectations, before = transition
                continue
            if segment not in {"installation", "reinstallation"}:
                return
            index = 0 if segment == "installation" else 1
            state = start(case.operations[index])
            publisher.publish_step(index, state)
            completed = self._step(
                case, executable, environment, expectations, before, writer, publisher, index, state
            )
            if completed is None:
                return
            expectations, before = completed

    def _step(
        self,
        case: EffectInstallCase,
        executable: Path,
        environment: EffectEnvironment,
        expectations: ExpectationSet,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        publisher: CasePublisher,
        index: int,
        state: StepState,
    ) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
        try:
            if index:
                with writer.measure("step_preparation", index):
                    previous = publisher.facts.steps[0].verification
                    assert previous is not None
                    if case.intermediate_preparation is None:
                        expectations = build_reinstall_expectations(expectations, before, previous)
                    observed = environment.observe(writer, "before", step_index=index)
                    usable = not observed.obstacles and same_observation(before, observed)
                    state = advance(
                        state, PreparationObserved(f"steps/{index}/before.json", usable)
                    )
                    if not usable:
                        raise ValueError(
                            "Environment changed or was obstructed before the second installation"
                        )
            else:
                state = advance(state, PreparationObserved(REFERENCES["before"]))
            state = advance(state, Prepared())
            if index and case.intermediate_preparation is None:
                writer.write_metadata(
                    f"expectations/{expectations.phase}.json", expectations.to_data()
                )
            state = advance(state, ExpectationsRetained(f"expectations/{expectations.phase}.json"))
            with writer.measure("command", index) as timing:
                command = self.driver.install(
                    case,
                    executable,
                    environment.project,
                    environment.home,
                    environment.project.parent.parent / "command-tmp",
                )
                timing.duration_seconds = command.duration_seconds
                if command.duration_seconds is None:
                    timing.state = "unavailable"
                    timing.diagnostic = "Command executor did not supply a duration"
            state = advance(
                state,
                CommandReturned(
                    {
                        "args": command.args,
                        "cwd": command.cwd,
                        "state": command.state,
                        "exit_code": command.exit_code,
                        "reason": command.reason,
                        "stdout_file": None,
                        "stderr_file": None,
                    }
                ),
            )
            retained = writer.write_command(command, step_index=index)
            assert retained["stdout_file"] is not None and retained["stderr_file"] is not None
            state = advance(
                state, CommandRetained(retained["stdout_file"], retained["stderr_file"])
            )
            publisher.publish_step(index, state)
            with writer.measure("checks", index):
                after = environment.observe(writer, "after", step_index=index)
                state = advance(state, ObservationRetained(f"steps/{index}/after.json"))
                verdict = self.verifier.verify(expectations, after)
                state = advance(state, VerificationComputed(verdict))
                writer.write_verification(verdict, step_index=index)
                state = advance(state, VerificationRetained(f"steps/{index}/verification.json"))
            state = advance(state, Terminate())
        except EvidenceWriteError:
            # Authority was not retained. Keep the previous declaration and stop all effects.
            writer.halted = True
            raise
        except (OSError, ValueError) as error:
            state = advance(state, StopStep(str(error)))
            writer.write_metadata(f"steps/{index}/failure.json", state.to_data())
            publisher.publish_step(index, state)
            return None
        publisher.publish_step(index, state)
        return (expectations, after) if status(state) == "passed" else None


class _InitialOperations:
    """Execute requested operations and keep their in-process outputs, without progression rules."""

    def __init__(
        self,
        case: EffectInstallCase,
        subject: Path,
        work: Path,
        writer: TestResultWriter,
        lifecycle: InitialPreparationLifecycle,
        verifier: EffectVerifier,
    ) -> None:
        self.case, self.subject, self.work = case, subject, work
        self.writer, self.lifecycle, self.verifier = writer, lifecycle, verifier
        self.environment: EffectEnvironment | None = None
        self.roots: dict[str, str] = {}
        self.sources: FilesystemSnapshot | None = None
        self.before: FilesystemSnapshot | None = None
        self.initial: ExpectationSet | None = None
        self.expectations: ExpectationSet | None = None

    def execute(self, operation: str) -> None:
        actions = {
            "environment": self.create_environment,
            "sources": self.capture_sources,
            "expectations": self.build_initial,
            "observation": self.observe_initial,
            "verification": self.verify_initial,
            "install_expectations": self.build_install,
        }
        actions[operation]()

    def create_environment(self) -> None:
        self.environment = EffectEnvironment(self.case, self.work / "environment")
        self.environment.prepare()
        (self.work / "command-tmp").mkdir()
        self.roots = {
            "home": str(self.environment.home),
            "project": str(self.environment.project),
        }
        self.lifecycle.acquire("environment")
        self.writer.write_metadata(REFERENCES["environment"], self.roots)
        self.lifecycle.retain("environment", REFERENCES["environment"])

    def capture_sources(self) -> None:
        assert self.environment is not None
        self.sources = self.environment.capture_sources(self.subject)
        self.lifecycle.acquire("sources")
        self.writer.write_snapshot(self.sources, "expected")
        self.lifecycle.retain("sources", REFERENCES["sources"])

    def build_initial(self) -> None:
        assert self.sources is not None
        self.initial = bind_roots(build_initial_expectations(self.case, self.sources), self.roots)
        self.lifecycle.acquire("expectations")
        self.writer.write_metadata(REFERENCES["expectations"], self.initial.to_data())
        self.lifecycle.retain("expectations", REFERENCES["expectations"])

    def observe_initial(self) -> None:
        assert self.environment is not None
        self.before = self.environment.capture_initial()
        self.lifecycle.acquire("observation")
        self.writer.write_initial_observation(self.before)
        self.lifecycle.retain("observation", REFERENCES["before"])

    def verify_initial(self) -> None:
        assert self.initial is not None and self.before is not None
        verdict = self.verifier.verify(self.initial, self.before)
        self.lifecycle.acquire(
            "verification",
            verification_passed=bool(
                verdict.complete and not verdict.mismatches and not verdict.obstacles
            ),
        )
        self.writer.write_initial_verification(verdict)
        self.lifecycle.retain("verification", REFERENCES["verification"])

    def build_install(self) -> None:
        assert self.sources is not None and self.before is not None
        self.expectations = build_install_expectations(
            self.case, self.sources, self.before, self.roots
        )
        self.lifecycle.acquire("install_expectations")
        self.writer.write_metadata(REFERENCES["install_expectations"], self.expectations.to_data())
        self.lifecycle.retain("install_expectations", REFERENCES["install_expectations"])
