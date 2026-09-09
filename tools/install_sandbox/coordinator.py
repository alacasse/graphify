"""Assemble the common first-install case from discovered target facts."""

from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.case import InstallTestCase, first_install_files
from tools.install_sandbox.container_harness import ContainerHarness, ContainerRunResult
from tools.install_sandbox.result_reader import read_result
from tools.install_sandbox.results import InstallTestResult
from tools.install_sandbox.spec import InstallTestSpec
from tools.install_sandbox.spec_reader import InstallSpecReader


@dataclass(frozen=True)
class FirstInstallResult:
    """Keep container execution, the validated case and transport diagnostics separate."""

    container: ContainerRunResult
    test: InstallTestResult | None
    result_error: str | None
    output_directory: Path

    @property
    def passed(self) -> bool:
        return (
            self.test is not None
            and self.test.status == "passed"
            and self.result_error is None
            and self.container.state == "completed"
            and self.container.cleanup_complete
        )


def _check_destinations(subject: Path, case_file: Path, output: Path) -> None:
    if subject.is_relative_to(output) or output.is_relative_to(subject):
        raise ValueError("Subject and evidence directories must be separate")
    if case_file.is_relative_to(subject) or case_file.is_relative_to(output):
        raise ValueError("Case file must be outside subject and evidence directories")
    if case_file.exists():
        raise ValueError("Case file must be fresh")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Evidence directory must be fresh or empty")


def _collect_result(
    container: ContainerRunResult, case: InstallTestCase, output: Path
) -> FirstInstallResult:
    try:
        result = read_result(output, case)
    except FileNotFoundError as error:
        return FirstInstallResult(container, None, f"Result unavailable: {error}", output)
    except OSError as error:
        return FirstInstallResult(container, None, f"Result unreadable: {error}", output)
    except ValueError as error:
        return FirstInstallResult(container, None, f"Result invalid: {error}", output)
    return FirstInstallResult(container, result, None, output)


class InstallTestCoordinator:
    def run_first_install(
        self,
        *,
        specs_directory: Path,
        target: str,
        subject_checkout: Path,
        case_file: Path,
        output_directory: Path,
        runtime_executable: str | Path = "docker",
        build_timeout_seconds: float = 300.0,
        run_timeout_seconds: float = 900.0,
        graceful_termination_seconds: float = 10.0,
    ) -> FirstInstallResult:
        """Conduct one discovered project case, then validate its result after cleanup."""
        subject, case_path, output = (
            path.expanduser().resolve() for path in (subject_checkout, case_file, output_directory)
        )
        _check_destinations(subject, case_path, output)
        case = self.write_first_install(specs_directory, target, case_path)
        container = ContainerHarness().run_case(
            subject_checkout=subject,
            case_file=case_path,
            output_directory=output,
            runtime_executable=runtime_executable,
            build_timeout_seconds=build_timeout_seconds,
            run_timeout_seconds=run_timeout_seconds,
            graceful_termination_seconds=graceful_termination_seconds,
        )
        return _collect_result(container, case, output)

    def write_first_install(
        self, specs_directory: Path, target: str, case_file: Path
    ) -> InstallTestCase:
        """Discover targets, assemble one project case and write its complete JSON."""
        specs = InstallSpecReader().read(specs_directory)
        if target not in specs:
            raise ValueError(f"Target not found in {specs_directory}: {target}")
        case = self.first_install(target, specs[target])
        case.write(case_file)
        return case

    def first_install(self, target: str, spec: InstallTestSpec) -> InstallTestCase:
        return InstallTestCase(
            name="first-install",
            target=target,
            scope="project",
            spec=spec,
            initial_files=first_install_files(spec),
            operations=["install"],
        )
