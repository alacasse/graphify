"""Output lifecycle integration through a controlled transport and real engine."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import arrange
from tools.install_sandbox.host.output_lifecycle import CampaignCommandResult, CampaignOutput

START = datetime(2026, 9, 17, 14, 30, 12, tzinfo=UTC)
RUNTIME = Path(__file__).with_name("fake_docker.py")


def arrange_output(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arrange(root)
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(root / "runtime"))
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(Path(__file__).with_name("native_case.py")))
    monkeypatch.setenv("FAKE_DOCKER_DISCARD_WORK", "1")


def refused(root: Path, now: datetime = START, output: Path | None = None) -> CampaignCommandResult:
    (root / "subject").mkdir(exist_ok=True)
    return CampaignOutput(managed_root=root / "out", now=lambda: now).run(
        spec_file=root / "missing-effects.yaml",
        subject_context_file=root / "context.json",
        subject_checkout=root / "subject",
        output_directory=output,
        runtime_executable=RUNTIME,
    )


def valid(root: Path, monkeypatch: pytest.MonkeyPatch) -> CampaignCommandResult:
    arrange_output(root, monkeypatch)
    return CampaignOutput(managed_root=root / "out", now=lambda: START).run(
        spec_file=root / "effects.yaml",
        subject_context_file=root / "context.json",
        subject_checkout=root / "subject",
        runtime_executable=RUNTIME,
    )
