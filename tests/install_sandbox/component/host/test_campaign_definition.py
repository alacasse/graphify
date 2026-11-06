"""Reject invalid definitions before output ownership and retain accepted inputs."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.host import campaign_definition, coordinator, output_lifecycle
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.output_lifecycle import CampaignOutput


def _invalidate_context(context: Path, fault: str) -> None:
    data = json.loads(context.read_text())
    if fault == "rules":
        data["rules"]["skill_lock"] = "unsupported"
    else:
        data["identity"] = "unencodable-\ud800"
    context.write_text(json.dumps(data))


def _invalidate_inputs(subject: Path, spec: Path, context: Path, fault: str) -> None:
    if fault == "missing-spec":
        spec.unlink()
    elif fault == "yaml":
        spec.write_text("effects: [")
    elif fault == "missing-context":
        context.unlink()
    elif fault == "json":
        context.write_text('{"identity":')
    elif fault in {"rules", "transport"}:
        _invalidate_context(context, fault)
    elif fault == "missing-checkout":
        shutil.rmtree(subject)
    elif fault == "file-checkout":
        shutil.rmtree(subject)
        subject.write_text("not a checkout")


@pytest.mark.parametrize(
    "fault",
    [
        "missing-spec",
        "yaml",
        "missing-context",
        "json",
        "rules",
        "transport",
        "missing-checkout",
        "file-checkout",
        "prepare-context",
    ],
)
def test_invalid_definition_never_allocates_or_runs_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    subject, spec, context = arrange(tmp_path)
    _invalidate_inputs(subject, spec, context, fault)
    allocate = Mock(side_effect=AssertionError("output allocation must not occur"))
    run = Mock(side_effect=AssertionError("runtime must not occur"))
    retention = Mock(side_effect=AssertionError("retention must not occur"))
    monkeypatch.setattr(output_lifecycle, "retain_finished", retention)
    monkeypatch.setattr("tools.install_sandbox.host.output_lifecycle._Session._allocate", allocate)
    monkeypatch.setattr(coordinator.InstallTestCoordinator, "run_campaign", run)
    result = CampaignOutput(managed_root=tmp_path / "out").run(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        prepare_only=fault == "prepare-context",
    )
    assert result.exit_code == 2 and result.output_directory is None
    assert result.report.execution == {} and result.report.writers == []
    assert not (tmp_path / "out").exists()
    retention.assert_not_called()
    allocate.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("markdown", [True, False])
def test_definition_retains_case_transports_after_inputs_disappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, markdown: bool
) -> None:
    subject, spec, context = arrange(tmp_path, markdown=markdown)
    before = set(tmp_path.rglob("*"))
    with monkeypatch.context() as loading:
        loading.setattr(
            subprocess, "run", Mock(side_effect=AssertionError("runtime during loading"))
        )
        definition = load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        )
    assert set(tmp_path.rglob("*")) == before
    spec.unlink()
    context.unlink()
    monkeypatch.setattr(
        campaign_definition, "build_effect_cases", Mock(side_effect=AssertionError("rebuilt cases"))
    )
    transport = ControlledTransport(tmp_path, markdown=markdown)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    proof = tmp_path / "proof"
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=proof
    )
    assert result.passed
    assert len(transport.installer.calls) == 2 * len(definition.built.cases)
    assert [
        (case.name, case.construction, case.construction_reason)
        for case in result.cases
        if case.construction != "constructed"
    ] == [(item.name, item.classification, item.reason) for item in definition.built.decisions]
    for case, serialized in zip(definition.built.cases, definition.transports, strict=True):
        assert (proof / "inputs" / f"{case.name}.json").read_text() == serialized
    phases = {timing.phase: timing for timing in result.timings}
    assert "construction" not in phases
    assert phases["materialization"].state == "measured"


def test_prepare_only_validates_context_but_skips_case_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = arrange(tmp_path)
    data = json.loads(context.read_text())
    data.update(package_root="graphify", revision="a" * 40)
    context.write_text(json.dumps(data))
    build = Mock(side_effect=AssertionError("prepare-only must not construct cases"))
    monkeypatch.setattr(campaign_definition, "build_effect_cases", build)
    before = set(tmp_path.rglob("*"))
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject, prepare_only=True
    )
    assert definition.built.cases == () and definition.transports == ()
    assert definition.built.decisions == ()
    assert set(tmp_path.rglob("*")) == before
    build.assert_not_called()


def test_supplied_construction_timing_is_preserved_separately_from_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.contracts.timings import Timing

    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    construction = Timing("construction", state="measured", duration_seconds=0.125)
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=tmp_path / "proof", construction_timing=construction
    )
    assert result.passed
    phases = {timing.phase: timing for timing in result.timings}
    assert phases["construction"] == construction
    assert phases["materialization"].state == "measured"
    assert phases["materialization"].duration_seconds is not None


def test_materialization_write_failure_keeps_evidence_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    transport = ControlledTransport(tmp_path)
    cleanup = Mock(wraps=transport.cleanup)
    prepare = Mock(wraps=transport.prepare)
    monkeypatch.setattr(transport, "cleanup", cleanup)
    monkeypatch.setattr(transport, "prepare", prepare)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    write = Path.write_text

    def fail_transport(path: Path, *args: object, **kwargs: object) -> int:
        if path.parent.name == "inputs":
            raise OSError("controlled materialization write failure")
        return write(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", fail_transport)
    proof = tmp_path / "proof"
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=definition, output_directory=proof
    )
    assert not result.passed
    assert result.error is not None and "materialization write failure" in result.error
    assert all(case.state == "not_run" for case in result.cases)
    assert (proof / "campaign.json").is_file()
    cleanup.assert_called_once()
    prepare.assert_not_called()


@pytest.mark.parametrize("destination", ["subject", "subject/nested"])
def test_direct_coordinator_protects_subject_before_harness_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    subject, spec, context = arrange(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    harness = Mock(side_effect=AssertionError("runtime must not be constructed"))
    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    before = set(subject.rglob("*"))
    with pytest.raises(ValueError):
        coordinator.InstallTestCoordinator().run_campaign(
            definition=definition, output_directory=tmp_path / destination
        )
    assert set(subject.rglob("*")) == before
    harness.assert_not_called()
