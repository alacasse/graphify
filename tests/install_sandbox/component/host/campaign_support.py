"""Controlled arrangements shared by sandbox behavior tests."""

import json
from pathlib import Path

from tools.install_sandbox.host.coordinator import CampaignResult, InstallTestCoordinator

COMPONENT = Path(__file__).parent


SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


def campaign(
    root: Path,
    names: tuple[str, ...] = ("first-install", "preserve-skill-backup"),
    *,
    timeout: float = 5,
) -> CampaignResult:
    return InstallTestCoordinator().run_campaign(
        specs_directory=SPECS,
        target="sandbox-reference",
        case_names=names,
        subject_checkout=root / "subject",
        output_directory=root / "campaign",
        runtime_executable=COMPONENT.parent / "host/fake_docker.py",
        build_timeout_seconds=timeout,
        verify_timeout_seconds=timeout,
        run_timeout_seconds=timeout,
        graceful_termination_seconds=0.1,
    )


def commands(root: Path) -> list[list[str]]:
    return [json.loads(p.read_text()) for p in sorted((root / "runtime").glob("command-*"))]
