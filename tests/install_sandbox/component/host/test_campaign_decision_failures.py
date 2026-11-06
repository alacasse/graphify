"""Construction decisions survive real coordinator failures without becoming runtime cases."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
import yaml

from tests.install_sandbox.component.host.native_support import (
    ControlledTransport,
    arrange,
    completed,
)
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.host import campaign_definition, coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.coordinator import CampaignResult
from tools.install_sandbox.host.docker_runtime import ContainerRunResult


def _arrange_decisions(root: Path, markdown_count: int) -> tuple[Path, Path, Path]:
    subject, spec, context = arrange(root, markdown=markdown_count > 0)
    if markdown_count == 2:
        data = cast(dict[str, Any], yaml.safe_load(spec.read_text()))
        second = copy.deepcopy(data["effects"][1])
        second["source"] = "second-instructions.md"
        second["destination"]["path"] = "SECOND.md"
        data["effects"].append(second)
        spec.write_text(yaml.safe_dump(data))
        (subject / "second-instructions.md").write_text("## graphify\nSecond synthetic map.\n")
    return subject, spec, context


def _transport(root: Path, markdown_count: int) -> ControlledTransport:
    transport = ControlledTransport(root, markdown=markdown_count > 0)
    if markdown_count != 2:
        return transport
    execute = transport.installer.execute

    def install_two(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute(args, project, environment, timeout)
        document = project / "SECOND.md"
        content = document.read_text()
        section = "## graphify\nSecond synthetic map.\n"
        if "Replace this placeholder." in content:
            document.write_text(
                content.replace("## graphify\nReplace this placeholder.\n\n", section)
            )
        elif "## graphify" not in content:
            document.write_text(content + "\n" + section)
        return result

    transport.installer.execute = install_two
    return transport


def _assert_decisions(result: CampaignResult, markdown_count: int) -> None:
    classification = "not_applicable" if markdown_count == 0 else "unconstructible"
    reason = (
        "No Markdown effect declared"
        if markdown_count == 0
        else "The case builder currently supports only one Markdown effect"
    )
    saved = json.loads((result.output_directory / "campaign.json").read_text())
    assert saved["version"] == 3
    text = (result.output_directory / "campaign.txt").read_text()
    label = "not applicable" if markdown_count == 0 else "applicable but not constructible"
    assert label in text and reason in text
    decisions = [entry for entry in result.cases if entry.construction != "constructed"]
    reports = {entry["name"]: entry for entry in saved["cases"]}
    assert [case.name for case in decisions] == ["missing-section", "altered-section"]
    assert (
        next(case for case in result.cases if case.name == "missing-reference").construction
        == "constructed"
    )
    for entry in decisions:
        report = reports[entry.name]
        assert entry.construction == report["construction"] == classification
        assert entry.construction_reason == report["construction_reason"] == reason
        assert entry.state is entry.result is entry.output_directory is None
        assert all(report[field] is None for field in ("state", "result", "output_directory"))
        assert not (result.output_directory / "cases" / entry.name).exists()
        assert not (result.output_directory / "inputs" / f"{entry.name}.json").exists()


@pytest.mark.parametrize("markdown_count", [0, 2])
@pytest.mark.parametrize(
    "fault",
    ["interruption", "exception", "run-interruption", "run-exception", "preparation", "cleanup"],
)
def test_decisions_survive_coordinator_failure_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, markdown_count: int, fault: str
) -> None:
    subject, spec, context = _arrange_decisions(tmp_path, markdown_count)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    transport = _transport(tmp_path, markdown_count)
    if fault in {"interruption", "exception", "run-interruption", "run-exception"}:
        error = KeyboardInterrupt() if "interruption" in fault else RuntimeError("Controlled fault")
        operation = "run_case" if fault.startswith("run-") else "prepare"
        monkeypatch.setattr(transport, operation, Mock(side_effect=error))
    elif fault == "preparation":
        monkeypatch.setattr(
            transport, "prepare", Mock(return_value=replace(completed(), state="failed"))
        )
    else:
        cleanup = transport.cleanup

        def incomplete_cleanup() -> ContainerRunResult:
            return replace(cleanup(), cleanup_complete=False)

        monkeypatch.setattr(transport, "cleanup", incomplete_cleanup)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof"
    )
    assert not result.passed and not result.successful
    assert result.status == "incomplete"
    saved = json.loads((result.output_directory / "campaign.json").read_text())
    assert saved["status"] == "incomplete" and saved["passed"] is False
    assert result.interrupted is ("interruption" in fault)
    assert len(transport.installer.calls) == (22 if fault == "cleanup" else 0)
    first = result.cases[0]
    if fault == "cleanup":
        assert first.state == "finished" and first.result is not None and first.result.passed
    else:
        assert first.state == ("incomplete" if fault.startswith("run-") else "not_run")
        assert first.result is None
    _assert_decisions(result, markdown_count)


def test_two_markdown_definition_retains_decisions_after_inputs_disappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = _arrange_decisions(tmp_path, 2)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    spec.unlink()
    context.unlink()
    monkeypatch.setattr(
        campaign_definition, "build_effect_cases", Mock(side_effect=AssertionError("rebuilt cases"))
    )
    transport = _transport(tmp_path, 2)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof"
    )
    assert not result.passed
    assert len(transport.installer.calls) == 22
    first = result.cases[0]
    assert first.result is not None and first.result.passed
    assert [
        (entry.construction, entry.construction_reason)
        for entry in result.cases
        if entry.construction != "constructed"
    ] == [(decision.classification, decision.reason) for decision in definition.built.decisions]
    for case, serialized in zip(definition.built.cases, definition.transports, strict=True):
        assert (tmp_path / "proof/inputs" / f"{case.name}.json").read_text() == serialized
    _assert_decisions(result, 2)
