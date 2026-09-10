"""Local command substitute: real case program, controlled package preparation only."""

import os
import sys
from pathlib import Path

# This adapter is a local test process, never an image payload or tested product.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.install_sandbox.container_main import main
from tools.install_sandbox.driver import InstallerDriver
from tools.install_sandbox.runner import InstallTestRunner

if __name__ == "__main__":
    subject, case, output = sys.argv[1:]
    raise SystemExit(
        main(
            [
                "--reference-sources",
                subject,
                "--prepared-executable",
                os.environ["CONTROLLED_INSTALLER"],
                "--case-file",
                case,
                "--output-directory",
                output,
                "--work-directory",
                str(Path(output).parents[2] / "work" / Path(output).name),
            ],
            runner=InstallTestRunner(InstallerDriver(timeout=2)),
        )
    )
