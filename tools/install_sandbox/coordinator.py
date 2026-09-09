"""Assemble the common first-install case from discovered target facts."""

from pathlib import Path

from tools.install_sandbox.case import InstallTestCase, first_install_files
from tools.install_sandbox.spec import InstallTestSpec
from tools.install_sandbox.spec_reader import InstallSpecReader


class InstallTestCoordinator:
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
