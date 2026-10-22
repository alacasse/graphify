"""Execute the native engine behind the controlled container command adapter."""

import sys
from pathlib import Path

# This test-only subprocess runs from the transport's temporary working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.install_sandbox.component.host.native_support import LiteralInstaller
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner

if __name__ == "__main__":
    source, case, output = map(Path, sys.argv[1:])
    InstallTestRunner(InstallerDriver(LiteralInstaller().execute)).run_case(
        reference_sources=source,
        prepared_executable=source.parent / "literal-installer",
        case_file=case,
        work_directory=output.parents[2] / "work" / "native",
        output_directory=output,
    )
