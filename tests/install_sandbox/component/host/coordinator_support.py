"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.host.coordinator import CoordinatedResult, InstallTestCoordinator

_COMPONENT = Path(__file__).parent


_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


def arrange_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "passed") -> None:
    LocalCase(tmp_path)
    (tmp_path / "case.json").unlink()
    executable = tmp_path / "controlled-installer"
    executable.write_text(controlled_script(mode), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv(
        "FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT.parent / "container/controlled_case.py")
    )
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_first(tmp_path: Path) -> CoordinatedResult:
    campaign = InstallTestCoordinator().run_campaign(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_names=["first-install"],
        subject_checkout=tmp_path / "subject",
        output_directory=tmp_path / "campaign",
        runtime_executable=_COMPONENT.parent / "host/fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )
    result = campaign.cases[0].result
    assert result is not None, campaign
    return result
