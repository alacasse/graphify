"""Explicit selections execute canonical cases and retain autonomous partial evidence."""

import copy
import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.result_reader import read_evidence


def arguments(subject: Path, spec: Path, context: Path, output: Path) -> list[str]:
    return [
        "--repo",
        str(subject),
        "--spec",
        str(spec),
        "--subject-context",
        str(context),
        "--output",
        str(output),
    ]


@pytest.mark.parametrize(
    "requested",
    [
        ["stale-version"],
        ["duplicate-json-hook", "stale-version", "missing-section"],
        None,
    ],
)
def test_selected_cli_executes_only_requested_cases_and_replays_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: list[str] | None,
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
    )
    catalogue = [entry.name for entry in definition.built.entries]
    if requested is None:
        requested = list(reversed(catalogue))
    elif len(requested) == 3:
        assert [name for name in catalogue if name in requested] == [
            "missing-section",
            "stale-version",
            "duplicate-json-hook",
        ]
    transport = ControlledTransport(tmp_path)
    run_case = Mock(wraps=transport.run_case)
    monkeypatch.setattr(transport, "run_case", run_case)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    args = arguments(subject, spec, context, output)
    for name in requested:
        args.extend(["--case", name])
    assert main(args) == 0
    expected = [name for name in catalogue if name in requested]
    assert [call.kwargs["case_file"].stem for call in run_case.call_args_list] == expected
    assert len(transport.installer.calls) == 2 * len(expected)
    report = json.loads((output / "campaign.json").read_text())
    assert report["scope"] == "partial"
    assert report["requested_cases"] == requested
    assert report["omitted_cases"] == [name for name in catalogue if name not in requested]
    assert report["executed_cases"] == expected
    assert report["status"] == "partial_passed"
    assert report["passed"] is False
    assert [case["name"] for case in report["cases"]] == expected
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert_archived_selection(output, report, requested, expected)


def assert_archived_selection(
    output: Path,
    report: dict[str, Any],
    requested: list[str],
    expected: list[str],
) -> None:
    restored = output.parent / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
        names = archive.namelist()
    archived = json.loads((restored / "evidence/campaign.json").read_text())
    for key in ("scope", "requested_cases", "omitted_cases", "executed_cases", "status", "passed"):
        assert archived[key] == report[key]
    for text in (
        (output / "campaign.txt").read_text(),
        (restored / "evidence/campaign.txt").read_text(),
    ):
        assert "partial" in text.lower()
        assert "Requested cases: " + ", ".join(requested) in text
        assert "Executed cases: " + ", ".join(expected) in text
        omitted = ", ".join(report["omitted_cases"]) or "none"
        assert "Omitted cases (not selected): " + omitted in text
    assert sorted(
        Path(name).stem
        for name in names
        if name.startswith("evidence/inputs/") and name.endswith(".json")
    ) == sorted(expected)
    for case in report["cases"]:
        reread = read_evidence(restored / "evidence/cases" / case["name"])
        decoded = asdict(reread)
        decoded["preparation"] = reread.preparation.to_data()
        decoded["steps"] = [step.to_data() for step in reread.steps]
        assert decoded == case["result"]["test"]


@pytest.mark.parametrize(
    "extra,diagnostic",
    [
        (["--case", "unknown-case"], "unknown-case"),
        (["--case", "reinstall", "--case", "reinstall"], "reinstall"),
        (["--case", "reinstall", "--prepare-only"], "prepare"),
    ],
)
def test_invalid_selection_fails_before_allocation_or_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    diagnostic: str,
) -> None:
    subject, spec, context = arrange(tmp_path)
    harness = Mock(side_effect=AssertionError("Runtime must not be allocated"))
    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    output = tmp_path / "published"
    assert main(arguments(subject, spec, context, output) + extra) == 2
    harness.assert_not_called()
    assert not output.exists()
    captured = capsys.readouterr()
    assert diagnostic in captured.err + captured.out


@pytest.mark.parametrize("mixed", [True, False])
def test_selected_nonapplicable_case_is_reported_without_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mixed: bool,
) -> None:
    subject, spec, context = arrange(tmp_path, markdown_only=True)
    transport = ControlledTransport(tmp_path, markdown_only=True)
    run_case = Mock(wraps=transport.run_case)
    monkeypatch.setattr(transport, "run_case", run_case)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    args = [*arguments(subject, spec, context, output), "--case", "stale-version"]
    if mixed:
        args += ["--case", "reinstall"]
    assert main(args) == (0 if mixed else 1)
    report = json.loads((output / "campaign.json").read_text())
    assert report["passed"] is False
    assert report["status"] == ("partial_passed" if mixed else "partial_incomplete")
    decision = next(case for case in report["cases"] if case["name"] == "stale-version")
    assert decision["construction"] == "not_applicable"
    assert decision["construction_reason"] == "No skill effect declared"
    assert decision["result"] is None
    assert run_case.call_count == int(mixed)
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        assert not any("/stale-version" in name for name in archive.namelist())


def test_selected_unconstructible_case_retains_reason_and_cannot_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, spec, context = arrange(tmp_path, markdown_only=True)
    raw = yaml.safe_load(spec.read_text())
    second = copy.deepcopy(raw["effects"][0])
    second["destination"]["path"] = "SECOND.md"
    raw["effects"].append(second)
    spec.write_text(yaml.safe_dump(raw))
    transport = ControlledTransport(tmp_path, markdown_only=True)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    assert main([*arguments(subject, spec, context, output), "--case", "missing-section"]) == 1
    report = json.loads((output / "campaign.json").read_text())
    assert report["status"] == "partial_incomplete"
    assert not report["passed"]
    assert report["cases"][0]["construction"] == "unconstructible"
    assert "only one Markdown effect" in report["cases"][0]["construction_reason"]
    assert transport.installer.calls == []


def test_selected_false_success_stays_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = arrange(tmp_path)
    transport = ControlledTransport(tmp_path)
    transport.installer.duplicate_hook_survivor = "all"
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    assert main([*arguments(subject, spec, context, output), "--case", "duplicate-json-hook"]) == 1
    report = json.loads((output / "campaign.json").read_text())
    assert not report["passed"]
    assert report["status"] != "partial_passed"
    assert report["cases"][0]["result"]["test"]["status"] == "failed"


def test_interruption_before_first_progress_retains_explicit_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
    )
    requested = ["stale-version", "missing-section"]
    omitted = [entry.name for entry in definition.built.entries if entry.name not in requested]
    interrupted = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(coordinator.InstallTestCoordinator, "run_campaign", interrupted)
    harness = Mock(side_effect=AssertionError("No runtime before coordinator progress"))
    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    output = tmp_path / "published"
    args = arguments(subject, spec, context, output)
    for name in requested:
        args.extend(["--case", name])
    assert main(args) == 130
    interrupted.assert_called_once()
    harness.assert_not_called()
    report = json.loads((output / "campaign.json").read_text())
    assert report["scope"] == "partial"
    assert report["requested_cases"] == requested
    assert report["omitted_cases"] == omitted
    assert report["executed_cases"] == []
    assert report["output_lifecycle"]["archive"] == "absent"
    assert report["output_lifecycle"]["raw_evidence"] is False
    assert not (output / "evidence.zip").exists()
    assert report["status"] == "partial_incomplete"
    assert report["passed"] is False
    text = (output / "campaign.txt").read_text()
    assert "Requested cases: " + ", ".join(requested) in text
    assert "Omitted cases (not selected): " + ", ".join(omitted) in text
    assert "Executed cases: none" in text
