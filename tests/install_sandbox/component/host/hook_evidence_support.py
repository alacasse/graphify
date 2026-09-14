"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import InstallTestCoordinator

_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


JSON = ".sandbox-reference/settings.json"


def run(tmp_path: Path, name: str, *, damage: str = "") -> tuple[InstallTestCase, Path]:
    local = LocalCase(tmp_path)
    case = InstallTestCoordinator().write_case(
        _SPECS, "sandbox-reference", tmp_path / "case.json", case_name=name
    )
    executable = local.prepare_executable()
    executable.write_text(controlled_script("passed") + damage)
    result = InstallTestRunner().run_case(
        reference_sources=tmp_path / "subject",
        prepared_executable=executable,
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "results",
    )
    assert result.status == ("failed" if damage else "passed"), result
    return case, tmp_path / "results"
