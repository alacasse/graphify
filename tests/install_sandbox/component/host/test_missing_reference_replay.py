"""Reference-removal evidence must reconstruct the requested physical action."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.test_missing_reference_run import conduct_reference
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.contracts.results import ArtifactReceipt
from tools.install_sandbox.host.result_reader import read_evidence
from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact


@pytest.mark.parametrize(
    "relative",
    [
        "intermediate/operation.json",
        "intermediate/performed.json",
        "intermediate/repair-plan.json",
        "intermediate/before.json",
        "intermediate/after.json",
        "intermediate/verification.json",
        "expectations/intermediate.json",
        "expectations/reinstall.json",
        "steps/0/after.json",
        "steps/1/after.json",
    ],
)
def test_missing_reference_proof_rejects_missing_artifact(tmp_path: Path, relative: str) -> None:
    result, _ = conduct_reference(tmp_path)
    assert result.status == "passed"
    (tmp_path / "proof" / relative).unlink()
    with pytest.raises((ValueError, OSError)):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_sha256", "0" * 64),
        ("document_sha256", "0" * 64),
        ("observation_ref", "steps/1/after.json"),
        (
            "destination",
            {"root": "project", "path": ".synthetic/skills/package/references/nested/reference.md"},
        ),
        ("destination", {"root": "home", "path": ".synthetic/skills/package/SKILL.md"}),
        ("format", "prepared-byte-range-v1"),
        ("kind", "markdown"),
    ],
)
def test_missing_reference_replay_rejects_forged_operation(
    tmp_path: Path, field: str, value: object
) -> None:
    conduct_reference(tmp_path)
    operation = tmp_path / "proof/intermediate/operation.json"
    payload = json.loads(operation.read_text())
    payload[field] = value
    operation.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize("reference", ["a/first.md", "nested/reference.md", "z-last.md"])
def test_reference_source_bytes_are_required_for_replay(tmp_path: Path, reference: str) -> None:
    conduct_reference(tmp_path, multiple=True)
    proof = tmp_path / "proof"
    # Locate the archived source rather than relying on its producer-owned archive prefix.
    candidates = [
        path for path in proof.rglob(Path(reference).name) if "reference-data" in path.parts
    ]
    assert candidates
    for path in candidates:
        path.write_text("Forged source bytes.\n")
    with pytest.raises(ValueError):
        read_evidence(proof)


@pytest.mark.parametrize(
    "reference,stage",
    [
        ("intermediate/operation.json", "started"),
        ("intermediate/repair-plan.json", "preparation_expectations_retained"),
        ("intermediate/before.json", "repair_plan_retained"),
        ("intermediate/performed.json", "before_retained"),
        ("intermediate/after.json", "mutation_recorded"),
        ("intermediate/verification.json", "after_retained"),
    ],
)
def test_reference_publication_interruption_blocks_reinstall_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: str, stage: str
) -> None:
    original = Writer.retain

    def interrupted(writer: Writer, artifact: JsonArtifact | SnapshotArtifact) -> ArtifactReceipt:
        if artifact.reference == reference:
            raise OSError("Controlled reference proof publication failure")
        return original(writer, artifact)

    monkeypatch.setattr(Writer, "retain", interrupted)
    result, installer = conduct_reference(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == stage
