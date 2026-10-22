"""Run the real engine with a literal, independent installed-package simulator."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.install_sandbox.component.host.native_support import LiteralInstaller
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner


class BoundInstaller(LiteralInstaller):
    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert args[0] == "/opt/install-sandbox/venv/bin/graphify"
        result = super().execute(args, project, environment, timeout)
        (Path(environment["HOME"]) / ".synthetic/skills/package/.graphify_version").write_text(
            "1.2.3"
        )
        return result


if __name__ == "__main__":
    source, case, output = map(Path, sys.argv[1:])
    InstallTestRunner(InstallerDriver(BoundInstaller().execute)).run_case(
        reference_sources=source,
        prepared_executable=Path("/opt/install-sandbox/venv/bin/graphify"),
        case_file=case,
        work_directory=output.parents[2] / "work/native",
        output_directory=output,
    )
