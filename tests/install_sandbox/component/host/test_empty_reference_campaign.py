"""An empty reference bundle blocks only its repair case and campaign success."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition


def _unavailable_sources(subject: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    if fault == "empty":
        (subject / "reference-data/nested/reference.md").unlink()
        (subject / "reference-data/nested").rmdir()
    else:
        capture = EffectEnvironment.capture_sources

        def incomplete(environment: EffectEnvironment, root: Path) -> FilesystemSnapshot:
            snapshot = capture(environment, root)
            # Restrict the incomplete observation to the reference repair cases.
            # Existing cases keep their independent execution and success.
            if environment.case.name in {
                "missing-reference",
                "altered-reference",
                "stale-reference",
            }:
                snapshot.contents.pop(("subject", "reference-data/nested/reference.md"))
                snapshot.obstacles.append(
                    {
                        "root": "subject",
                        "path": "reference-data/nested/reference.md",
                        "operation": "read_file",
                        "reason": "Controlled incomplete source inventory",
                    }
                )
            return snapshot

        monkeypatch.setattr(EffectEnvironment, "capture_sources", incomplete)


@pytest.mark.parametrize("fault", ["empty", "incomplete"])
def test_unavailable_reference_bundle_leaves_campaign_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    subject, spec, context = arrange(tmp_path)
    _unavailable_sources(subject, monkeypatch, fault)
    transport = ControlledTransport(tmp_path)
    execute = transport.installer.execute

    def install_empty_skill(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute(args, project, environment, timeout)
        reference = (
            Path(environment["HOME"]) / ".synthetic/skills/package/references/nested/reference.md"
        )
        if fault == "empty":
            reference.unlink()
            reference.parent.rmdir()
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
    blocked = ["missing-reference", "altered-reference"] + (
        ["stale-reference"] if fault == "incomplete" else []
    )
    for name in blocked:
        repair = cases.pop(name)
        assert repair.result is not None and repair.result.test is not None
        test = repair.result.test
        assert test.status == "not_run"
        assert test.preparation.checkpoint == "stopped"
        assert test.preparation.stop is not None
        assert test.preparation.stop.category == "validation"
        assert all(step.facts.command is None for step in test.steps)
    assert len(transport.installer.calls) == (20 if fault == "empty" else 18)
    assert set(cases) == {
        "reinstall",
        "missing-section",
        "altered-section",
        "altered-skill",
        "preserve-skill-backup",
        "stale-version",
        "missing-json-hook",
        "altered-json-hook",
        "duplicate-json-hook",
    } | ({"stale-reference"} if fault == "empty" else set())
    for case in cases.values():
        assert case.result is not None and case.result.passed


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_stale_reference_source_collision_stops_before_first_installer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    subject, spec, context = arrange(tmp_path)
    collision = subject / "reference-data/stale.md"
    if kind == "file":
        collision.write_bytes(b"This reference belongs to the package.\n")
    else:
        collision.mkdir()
    transport = ControlledTransport(tmp_path)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        ),
        output_directory=tmp_path / "proof",
    )
    stale = next(case for case in result.cases if case.name == "stale-reference")
    assert stale.result is not None and stale.result.test is not None
    test = stale.result.test
    assert test.status == "not_run"
    assert test.preparation.stop is not None
    assert test.preparation.stop.category == "validation"
    assert all(step.facts.command is None for step in test.steps)
