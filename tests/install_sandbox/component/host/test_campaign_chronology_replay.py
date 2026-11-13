"""Concordant host summaries cannot authorize an impossible execution order."""

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Literal
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.campaign_replay import replay_campaign
from tools.install_sandbox.host.coordinator import CampaignResult
from tools.install_sandbox.host.output_archive import export_summary


@pytest.fixture
def campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CampaignResult:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        requested_cases=("reinstall", "missing-reference"),
    )
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof"
    )
    assert result.successful and len(result.cases) == 2
    return result


def _archive(campaign: CampaignResult, name: str) -> Path:
    root = campaign.output_directory
    before = {
        path.relative_to(root): path.read_bytes()
        for path in (root / "cases").rglob("*")
        if path.is_file()
    }
    # Recompute every aggregate and host receipt from the altered host history.
    campaign.save()
    export_summary(root)
    assert before == {
        path.relative_to(root): path.read_bytes()
        for path in (root / "cases").rglob("*")
        if path.is_file()
    }
    archive = root.parent / (name + ".zip")
    with ZipFile(archive, "w") as output:
        for path in sorted(root.rglob("*")):
            output.write(path, "evidence/" + path.relative_to(root).as_posix())
    return archive


def _not_started(
    campaign: CampaignResult, start: int, state: Literal["pending", "not_run"]
) -> None:
    for entry in campaign.cases[start:]:
        assert entry.output_directory is not None
        shutil.rmtree(entry.output_directory)
        entry.output_directory.mkdir()
        entry.state, entry.result = state, None
        entry.not_run_reason = "Campaign stopped" if state == "not_run" else None


@pytest.mark.parametrize("preparation", ["missing", "incomplete", "cleanup"])
@pytest.mark.parametrize("suffix", ["pending", "not_run"])
def test_replay_rejects_case_started_after_unavailable_preparation(
    campaign: CampaignResult, preparation: str, suffix: Literal["pending", "not_run"]
) -> None:
    assert campaign.preparation is not None
    campaign.preparation = (
        None
        if preparation == "missing"
        else replace(
            campaign.preparation,
            state="incomplete",
            cleanup_complete=preparation != "cleanup",
        )
    )
    first = campaign.cases[0]
    with pytest.raises(
        ValueError, match="Common preparation.*contradictory started CaseKey"
    ) as error:
        replay_campaign(_archive(campaign, "impossible-preparation"))
    assert first.key is not None and first.key.operation in str(error.value)
    _not_started(campaign, 0, suffix)
    report = replay_campaign(_archive(campaign, "stopped-preparation"))
    assert report["executed_cases"] == [] and not report["successful"]


@pytest.mark.parametrize("stop", ["cleanup", "interrupted"])
@pytest.mark.parametrize("suffix", ["pending", "not_run"])
def test_replay_rejects_case_started_after_container_stop(
    campaign: CampaignResult, stop: str, suffix: Literal["pending", "not_run"]
) -> None:
    first, second = campaign.cases
    assert first.result is not None
    first.result = replace(
        first.result,
        container=replace(
            first.result.container,
            state="interrupted" if stop == "interrupted" else "incomplete",
            cleanup_complete=stop != "cleanup",
        ),
    )
    cause = "cleanup incomplete" if stop == "cleanup" else "interrupted"
    with pytest.raises(
        ValueError, match=f"Previous container {cause}.*contradictory started CaseKey"
    ) as error:
        replay_campaign(_archive(campaign, "impossible-container"))
    assert second.key is not None and second.key.operation in str(error.value)
    _not_started(campaign, 1, suffix)
    report = replay_campaign(_archive(campaign, "stopped-container"))
    assert report["executed_cases"] == [first.name] and not report["successful"]


@pytest.mark.parametrize("state", ["running", "incomplete"])
def test_replay_detects_container_start_before_first_installer_command(
    campaign: CampaignResult, state: Literal["running", "incomplete"]
) -> None:
    campaign.preparation = None
    _not_started(campaign, 0, "pending")
    campaign.cases[0].state = state
    assert campaign.executed_cases == []
    with pytest.raises(
        ValueError, match="Common preparation missing.*contradictory started CaseKey"
    ):
        replay_campaign(_archive(campaign, "started-without-command"))


@pytest.mark.parametrize("state", ["running", "incomplete", "pending", "not_run"])
def test_later_case_needs_previous_container_receipt(
    campaign: CampaignResult, state: Literal["running", "incomplete", "pending", "not_run"]
) -> None:
    first, second = campaign.cases
    assert first.output_directory is not None and second.key is not None
    shutil.rmtree(first.output_directory)
    first.output_directory.mkdir()
    first.state, first.result = state, None
    first.not_run_reason = "Campaign stopped" if state == "not_run" else None
    with pytest.raises(
        ValueError, match=f"Previous case {state} without a container receipt"
    ) as error:
        replay_campaign(_archive(campaign, "out-of-order"))
    assert str(second.key.to_data()) in str(error.value)
    _not_started(campaign, 1, "pending")
    assert replay_campaign(_archive(campaign, "intermediate"))["executed_cases"] == []


def test_product_failure_with_successful_cleanup_allows_next_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        requested_cases=("missing-json-hook",),
    )
    transport = ControlledTransport(tmp_path)
    transport.installer.hooks = False
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof"
    )
    assert len(result.cases) == 2
    assert all(
        entry.result and entry.result.test and entry.result.test.status == "failed"
        for entry in result.cases
    )
    assert replay_campaign(_archive(result, "product-failure"))["executed_cases"] == [
        entry.name for entry in result.cases
    ]
