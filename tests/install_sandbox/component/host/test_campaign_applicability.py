"""Campaign success requires every applicable case and consistent construction decisions."""

from dataclasses import replace
from pathlib import Path
from typing import Literal
from unittest.mock import Mock

import pytest

from tests.install_sandbox.component.host.native_support import (
    ControlledTransport,
    arrange,
    completed,
)
from tools.install_sandbox.contracts.effect_case import CaseNonConstruction, EffectCaseBuild
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.coordinator import CampaignCase, CampaignResult


@pytest.fixture
def passed_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CampaignResult:
    subject, spec, context = arrange(tmp_path)
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        ),
        output_directory=tmp_path / "proof",
    )
    assert result.passed
    return result


@pytest.mark.parametrize("state", ["pending", "running", "not_run", "incomplete", "finished"])
@pytest.mark.parametrize("retain_result", [True, False])
def test_only_finished_cases_with_results_can_pass(
    passed_campaign: CampaignResult, state: str, retain_result: bool
) -> None:
    entry = passed_campaign.cases[0]
    entry.state = state  # type: ignore[assignment]
    if not retain_result:
        entry.result = None
    assert passed_campaign.passed is (state == "finished" and retain_result)
    assert passed_campaign.cases[1].result is not None
    assert passed_campaign.cases[1].result.passed


@pytest.mark.parametrize("fault", ["failed", "unreadable", "cleanup", "interrupted", "path"])
def test_coordinated_result_failures_block_success(
    passed_campaign: CampaignResult, fault: str
) -> None:
    entry = passed_campaign.cases[0]
    result = entry.result
    assert result is not None and result.test is not None
    if fault == "failed":
        entry.result = replace(result, test=replace(result.test, status="failed"))
    elif fault == "unreadable":
        entry.result = replace(result, test=None, result_error="Result unreadable")
    elif fault == "cleanup":
        entry.result = replace(result, container=replace(result.container, cleanup_complete=False))
    elif fault == "interrupted":
        entry.result = replace(result, container=replace(result.container, state="interrupted"))
    else:
        entry.result = replace(result, output_directory=Path("unrelated"))
    assert not passed_campaign.successful
    assert passed_campaign.payload()["status"] == "incomplete"


@pytest.mark.parametrize("fault", ["interrupted", "error", "preparation", "cleanup", "entry-error"])
def test_execution_guards_still_block_success(passed_campaign: CampaignResult, fault: str) -> None:
    if fault == "interrupted":
        passed_campaign.interrupted = True
    elif fault == "error":
        passed_campaign.error = "Controlled error"
    elif fault == "entry-error":
        passed_campaign.cases[0].error = "Controlled case error"
    else:
        setattr(passed_campaign, fault, replace(completed(), cleanup_complete=False))
    assert not passed_campaign.passed


def nonconstructed(
    classification: Literal["not_applicable", "unconstructible"] = "not_applicable",
) -> CampaignCase:
    return CampaignCase(
        "missing-section",
        None,
        state=None,
        construction=classification,
        construction_reason="Controlled non-construction reason",
    )


@pytest.mark.parametrize("classification", ["not_applicable", "unconstructible"])
def test_no_constructed_cases_cannot_pass(
    tmp_path: Path, classification: Literal["not_applicable", "unconstructible"]
) -> None:
    campaign = CampaignResult(tmp_path, [], preparation=completed(), cleanup=completed())
    assert not campaign.passed
    campaign.cases = [nonconstructed(classification)]
    assert not campaign.passed


@pytest.mark.parametrize("classification", ["not_applicable", "unconstructible"])
def test_only_nonapplicable_decisions_can_be_excluded_from_success(
    passed_campaign: CampaignResult,
    classification: Literal["not_applicable", "unconstructible"],
) -> None:
    passed_campaign.cases = [passed_campaign.cases[0], nonconstructed(classification)]
    assert passed_campaign.passed is (classification == "not_applicable")


@pytest.mark.parametrize("field", ["result", "state", "output_directory", "construction_reason"])
def test_invalid_nonconstruction_is_rejected(passed_campaign: CampaignResult, field: str) -> None:
    decision = nonconstructed()
    values = {
        "result": passed_campaign.cases[0].result,
        "state": "finished",
        "output_directory": Path("unexpected"),
        "construction_reason": " ",
    }
    setattr(decision, field, values[field])
    passed_campaign.cases = [passed_campaign.cases[0], decision]
    assert not passed_campaign.passed
    with pytest.raises(ValueError):
        decision.validate()


def test_duplicate_entries_cannot_pass(passed_campaign: CampaignResult) -> None:
    passed_campaign.cases.append(passed_campaign.cases[0])
    assert not passed_campaign.passed


@pytest.mark.parametrize(
    "fault", ["missing-case", "extra-case", "duplicate-entry", "decision-overlap"]
)
def test_contradictory_case_associations_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    changed = False

    def contradict(result: CampaignResult) -> None:
        nonlocal changed
        if changed:
            return
        changed = True
        if fault == "missing-case":
            result.cases.append(CampaignCase("unknown-case", tmp_path / "unknown"))
        elif fault == "extra-case":
            result.cases.pop()
        elif fault == "duplicate-entry":
            result.cases.append(result.cases[0])
        else:
            result.cases[1] = nonconstructed()

    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof", progress=contradict
    )
    assert not result.passed and result.error is not None
    assert "ValueError" in result.error
    assert transport.installer.calls == []


def test_build_rejects_duplicate_or_overlapping_names(tmp_path: Path) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    case = definition.built.cases[0]
    with pytest.raises(ValueError, match="Duplicate"):
        EffectCaseBuild((case, case), ())
    decision = CaseNonConstruction(case.name, "not_applicable", "Controlled reason")
    with pytest.raises(ValueError, match="Duplicate"):
        EffectCaseBuild((case,), (decision,))
    with pytest.raises(ValueError, match="Duplicate"):
        EffectCaseBuild((), (decision, decision))


def test_reordered_entries_execute_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))

    def reorder(result: CampaignResult) -> None:
        result.cases.reverse()

    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof", progress=reorder
    )
    assert result.passed
    assert len(transport.installer.calls) == 12
    for entry in result.cases:
        assert entry.result is not None and entry.result.test is not None
        assert entry.result.test.case["name"] == entry.name
