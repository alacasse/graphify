"""Prove the native user command through host, engine, archive and autonomous reread."""

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.result_reader import read_evidence


@pytest.mark.parametrize("markdown_only", [False, True])
def test_cli_real_engine_and_autonomous_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, markdown_only: bool
) -> None:
    subject, spec, context = arrange(tmp_path, markdown_only=markdown_only)
    transport = ControlledTransport(tmp_path, markdown_only=markdown_only)

    def harness(**kwargs: object) -> ControlledTransport:
        return transport

    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    output = tmp_path / "published"
    assert (
        main(
            [
                "--spec",
                str(spec),
                "--subject-context",
                str(context),
                "--repo",
                str(subject),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert len(transport.installer.calls) == 4
    assert not (output / "evidence").exists()
    report = json.loads((output / "campaign.json").read_text())
    assert [case["name"] for case in report["cases"]] == ["reinstall", "missing-section"]
    saved = {case["name"]: case["result"]["test"] for case in report["cases"]}
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert not transport.executable.exists()
    assert not (tmp_path / "environment").exists()
    restored = tmp_path / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
    for name in ("reinstall", "missing-section"):
        reread = read_evidence(restored / "evidence/cases" / name)
        assert reread.status == "passed"
        assert asdict(reread) == saved[name]


def test_unavailable_case_reason_is_retained_in_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    subject, spec, context = arrange(tmp_path)
    data = yaml.safe_load(spec.read_text())
    data["effects"] = [effect for effect in data["effects"] if effect["kind"] != "markdown-section"]
    spec.write_text(yaml.safe_dump(data))
    transport = ControlledTransport(tmp_path)

    def harness(**kwargs: object) -> ControlledTransport:
        return transport

    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    result = coordinator.InstallTestCoordinator().run_campaign(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        output_directory=tmp_path / "proof",
    )
    unavailable = next(case for case in result.cases if case.name == "missing-section")
    assert unavailable.state == "not_run"
    assert unavailable.not_run_reason == "Requires exactly one Markdown section effect"
    assert not result.passed
    saved = json.loads((tmp_path / "proof/campaign.json").read_text())
    assert saved["cases"][1]["not_run_reason"] == unavailable.not_run_reason
