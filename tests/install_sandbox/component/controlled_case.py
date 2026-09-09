"""Local command substitute: real case program, controlled package preparation only."""

import os
import shutil
import sys
from pathlib import Path

# This adapter is a local test process, never an image payload or tested product.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.install_sandbox.container_main import main
from tools.install_sandbox.driver import InstallerCommandResult, InstallerDriver, execute_command
from tools.install_sandbox.preparer import GraphifyPreparer
from tools.install_sandbox.runner import InstallTestRunner


def prepare(
    args: list[str], cwd: Path, environment: dict[str, str], timeout: float
) -> InstallerCommandResult:
    code = "print('controlled package preparation')"
    if os.environ.get("CONTROLLED_PREPARATION_FAIL") == "1":
        code += "; raise SystemExit(9)"
    result = execute_command([sys.executable, "-c", code], cwd, environment, timeout)
    if "pip" in args:
        executable = cwd.parent / "venv/bin/graphify"
        executable.parent.mkdir(parents=True)
        shutil.copyfile(os.environ["CONTROLLED_INSTALLER"], executable)
        executable.chmod(0o755)
    return result


if __name__ == "__main__":
    subject, case, output = sys.argv[1:]
    raise SystemExit(
        main(
            [
                "--subject-checkout",
                subject,
                "--case-file",
                case,
                "--output-directory",
                output,
                "--work-directory",
                str(Path(output).parent / "work"),
            ],
            runner=InstallTestRunner(GraphifyPreparer(prepare), InstallerDriver(timeout=2)),
        )
    )
