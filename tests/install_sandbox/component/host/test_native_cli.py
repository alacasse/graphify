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
    assert len(transport.installer.calls) == 2
    assert not (output / "evidence").exists()
    report = json.loads((output / "campaign.json").read_text())
    saved = report["cases"][0]["result"]["test"]
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert not transport.executable.exists()
    assert not (tmp_path / "environment").exists()
    restored = tmp_path / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
    reread = read_evidence(restored / "evidence/cases/reinstall")
    assert reread.status == "passed"
    assert asdict(reread) == saved
