"""Reference-append evidence must reconstruct the requested physical action."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.test_altered_skill_run import (
    conduct_altered_skill,
)
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
def test_altered_skill_proof_rejects_missing_artifact(tmp_path: Path, relative: str) -> None:
    result, _ = conduct_altered_skill(tmp_path)
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
            {"root": "project", "path": ".synthetic/skills/package/SKILL.md"},
        ),
        (
            "destination",
            {"root": "home", "path": ".synthetic/skills/package/references/nested/reference.md"},
        ),
        ("format", "prepared-byte-range-v1"),
        ("kind", "markdown"),
        ("suffix", ""),
        ("suffix", "Rm9yZ2VkIHN1ZmZpeA=="),
    ],
)
def test_altered_skill_replay_rejects_forged_operation(
    tmp_path: Path, field: str, value: object
) -> None:
    conduct_altered_skill(tmp_path)
    operation = tmp_path / "proof/intermediate/operation.json"
    payload = json.loads(operation.read_text())
    payload[field] = value
    operation.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize("reference", ["nested/reference.md"])
def test_reference_source_bytes_are_required_for_replay(tmp_path: Path, reference: str) -> None:
    conduct_altered_skill(tmp_path, multiple=True)
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
            raise OSError("Controlled altered-skill proof publication failure")
        return original(writer, artifact)

    monkeypatch.setattr(Writer, "retain", interrupted)
    result, installer = conduct_altered_skill(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == stage


@pytest.mark.parametrize(
    "relative,field,value",
    [
        ("intermediate/performed.json", "document_sha256", "0" * 64),
        ("intermediate/verification.json", "complete", False),
        ("expectations/intermediate.json", "allowed_changes", []),
        ("expectations/reinstall.json", "allowed_changes", []),
        ("intermediate/repair-plan.json", "allowed_changes", []),
        ("steps/1/verification.json", "complete", False),
        ("result.json", "status", "failed"),
    ],
)
def test_altered_skill_replay_rejects_forged_retained_facts(
    tmp_path: Path, relative: str, field: str, value: object
) -> None:
    conduct_altered_skill(tmp_path)
    path = tmp_path / "proof" / relative
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize("phase", ["before", "after"])
def test_altered_skill_replay_rejects_changed_observation_bytes(tmp_path: Path, phase: str) -> None:
    conduct_altered_skill(tmp_path)
    path = tmp_path / f"proof/intermediate/{phase}/home" / ".synthetic/skills/package/SKILL.md"
    path.write_bytes(b"Forged observed reference.\n")
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


@pytest.fixture
def literal_proof(tmp_path: Path) -> Path:
    # Independently authored JSON, bytes, expectations and hashes; no producer runs.
    # Only unchanged lifecycle transport fields are shared with the Markdown fixture.
    payload = json.loads(
        (Path(__file__).parents[2] / "fixtures/retained-altered-skill-proof.json").read_text()
    )
    for relative, content in payload.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_literal_altered_skill_proof_replays_without_producer(literal_proof: Path) -> None:
    assert read_evidence(literal_proof).status == "passed"
    operation = json.loads((literal_proof / "intermediate/operation.json").read_text())
    assert operation["destination"] == {"root": "home", "path": "package/SKILL.md"}
    assert (literal_proof / "intermediate/after/home/package/SKILL.md").read_bytes() == (
        b"# Independent skill\n\nSandbox skill repair witness.\n"
    )


@pytest.mark.parametrize(
    "relative",
    [
        "intermediate/operation.json",
        "expectations/intermediate.json",
        "intermediate/repair-plan.json",
        "intermediate/before.json",
        "intermediate/performed.json",
        "intermediate/after.json",
        "intermediate/verification.json",
        "expectations/reinstall.json",
        "expected.json",
        "expected/refs/a.txt",
        "expected/refs/z.txt",
        "steps/0/after.json",
        "steps/1/after.json",
    ],
)
def test_literal_altered_skill_proof_requires_retained_inputs(
    literal_proof: Path, relative: str
) -> None:
    (literal_proof / relative).unlink()
    with pytest.raises(ValueError):
        read_evidence(literal_proof)


@pytest.mark.parametrize(
    "relative,field,value",
    [
        ("intermediate/operation.json", "case_sha256", "0" * 64),
        ("intermediate/operation.json", "observation_ref", "steps/1/after.json"),
        ("intermediate/operation.json", "suffix", "Rm9yZ2Vk"),
        ("intermediate/performed.json", "document_sha256", "0" * 64),
        ("expectations/intermediate.json", "allowed_changes", []),
        ("expectations/reinstall.json", "allowed_changes", []),
        ("intermediate/repair-plan.json", "allowed_changes", []),
        ("intermediate/verification.json", "complete", False),
        ("result.json", "status", "failed"),
    ],
)
def test_literal_altered_skill_proof_rejects_forgery(
    literal_proof: Path, relative: str, field: str, value: object
) -> None:
    path = literal_proof / relative
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(literal_proof)
