"""Present repair expectations must be validated even when repair never starts."""

import base64
import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.test_altered_section_run import (
    conduct as conduct_altered,
)
from tests.install_sandbox.component.container.test_missing_section_run import (
    conduct as conduct_missing,
)
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import ArtifactReceipt, InstallTestResult
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence
from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact


@pytest.fixture
def stopped_archive(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, InstallTestResult]:
    """Use literal installers; fail preparation or interrupt its after observation."""
    scenario, status = request.param
    observe = EffectEnvironment.observe_intermediate

    def stop(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
        if phase == "after":
            if status == "incomplete":
                raise OSError("Controlled interruption before preparation observation")
            (environment.project / "foreign-file").write_bytes(b"Unexpected preparation effect.\n")
        return observe(environment, phase)

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", stop)
    conduct = conduct_missing if scenario == "missing-section" else conduct_altered
    result, installer = conduct(tmp_path)
    assert result.status == status
    assert len(installer.calls) == 1
    assert result.steps[1]["progress"] == "not_started"
    # conduct removes all live inputs before replaying the archive itself.
    assert not (tmp_path / "subject").exists()
    assert not (tmp_path / "work").exists()
    assert not (tmp_path / "case.json").exists()
    assert (tmp_path / "proof/intermediate/repair-plan.json").is_file()
    return tmp_path / "proof", result


STOPPED_CASES = [
    (scenario, status)
    for scenario in ("missing-section", "altered-section")
    for status in ("failed", "incomplete")
]


@pytest.mark.parametrize("stopped_archive", STOPPED_CASES, indirect=True)
def test_honest_stopped_preparation_replays_after_cleanup(
    stopped_archive: tuple[Path, InstallTestResult],
) -> None:
    proof, original = stopped_archive
    assert read_evidence(proof) == original


@pytest.mark.parametrize("stopped_archive", STOPPED_CASES, indirect=True)
@pytest.mark.parametrize("tampering", ["malformed-json", "forged-source"])
def test_stopped_preparation_rejects_present_forged_repair_expectations(
    stopped_archive: tuple[Path, InstallTestResult], tampering: str
) -> None:
    proof, _ = stopped_archive
    retained = proof / "intermediate/repair-plan.json"
    if tampering == "malformed-json":
        retained.write_text("{this is not JSON", encoding="utf-8")
    else:
        data = json.loads(retained.read_text())
        constraints = [item for item in data["expectations"] if item["kind"] == "markdown-composed"]
        assert len(constraints) == 1
        constraints[0]["content"] = base64.b64encode(b"## graphify\nForged source.\n").decode()
        retained.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize("tampering", ["malformed-json", "forged-source"])
def test_effective_expectations_ahead_of_checkpoint_are_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, tampering: str
) -> None:
    retain = ResultWriter.retain

    def interrupted(
        writer: ResultWriter, artifact: JsonArtifact | SnapshotArtifact
    ) -> ArtifactReceipt:
        receipt = retain(writer, artifact)
        if artifact.reference == "expectations/reinstall.json":
            raise OSError("Interrupted after effective expectations publication")
        return receipt

    monkeypatch.setattr(ResultWriter, "retain", interrupted)
    conduct = conduct_missing if scenario == "missing-section" else conduct_altered
    result, installer = conduct(tmp_path)
    assert result.status == "incomplete"
    assert len(installer.calls) == 1
    assert result.steps[1]["progress"] == "not_started"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == "verification_retained"
    proof = tmp_path / "proof"
    assert read_evidence(proof) == result
    retained = proof / "expectations/reinstall.json"
    if tampering == "malformed-json":
        retained.write_text("{not JSON", encoding="utf-8")
    else:
        data = json.loads(retained.read_text())
        constraints = [item for item in data["expectations"] if item["kind"] == "markdown-composed"]
        assert len(constraints) == 1
        constraints[0]["content"] = base64.b64encode(b"## graphify\nForged source.\n").decode()
        retained.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)
