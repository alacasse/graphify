"""An empty reference bundle blocks only its repair case and campaign success."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition


def test_empty_reference_bundle_leaves_campaign_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = arrange(tmp_path)
    (subject / "reference-data/nested/reference.md").unlink()
    transport = ControlledTransport(tmp_path)
    execute = transport.installer.execute

    def install_empty_skill(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute(args, project, environment, timeout)
        reference = (
            Path(environment["HOME"]) / ".synthetic/skills/package/references/nested/reference.md"
        )
        reference.unlink()
        return result

    monkeypatch.setattr(transport.installer, "execute", install_empty_skill)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        ),
        output_directory=tmp_path / "proof",
    )
    assert not result.passed
    assert result.status == "incomplete"
    cases = {case.name: case for case in result.cases}
    repair = cases.pop("missing-reference")
    assert repair.result is not None and repair.result.test is not None
    test = repair.result.test
    assert test.status == "not_run"
    assert test.preparation.checkpoint == "stopped"
    assert test.preparation.stop is not None
    assert test.preparation.stop.category == "validation"
    assert all(step.facts.command is None for step in test.steps)
    assert len(transport.installer.calls) == 6
    assert set(cases) == {"reinstall", "missing-section", "altered-section"}
    for case in cases.values():
        assert case.result is not None and case.result.passed
