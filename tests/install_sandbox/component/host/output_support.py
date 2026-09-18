"""Small arrangements through the user campaign interface."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.campaign_support import COMPONENT, SPECS
from tests.install_sandbox.component.host.coordinator_support import arrange_first
from tools.install_sandbox.host.output_lifecycle import CampaignCommandResult, CampaignOutput

START = datetime(2026, 9, 17, 14, 30, 12, tzinfo=UTC)
RUNTIME = COMPONENT / "fake_docker.py"


def refused(root: Path, now: datetime = START, output: Path | None = None) -> CampaignCommandResult:
    (root / "subject").mkdir(exist_ok=True)
    return CampaignOutput(managed_root=root / "out", now=lambda: now).run(
        specs_directory=SPECS,
        target="missing",
        subject_checkout=root / "subject",
        output_directory=output,
        runtime_executable=RUNTIME,
    )


def valid(root: Path, monkeypatch: pytest.MonkeyPatch) -> CampaignCommandResult:
    arrange_first(root, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_DISCARD_WORK", "1")
    return CampaignOutput(managed_root=root / "out", now=lambda: START).run(
        specs_directory=SPECS,
        target="sandbox-reference",
        case_names=["first-install"],
        subject_checkout=root / "subject",
        runtime_executable=RUNTIME,
    )
