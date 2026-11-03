"""Archive-only rejection of missing, forged and misclassified transition proofs."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.test_missing_section_run import conduct
from tools.install_sandbox.contracts.results import ArtifactReceipt
from tools.install_sandbox.host.result_reader import read_evidence
from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact


def rewrite(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize(
    "relative",
    [
        "intermediate/operation.json",
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
def test_lost_required_proof_cannot_replay_as_success(tmp_path: Path, relative: str) -> None:
    conduct(tmp_path)
    (tmp_path / "proof" / relative).unlink()
    with pytest.raises((ValueError, OSError)):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_sha256", "0" * 64),
        ("document_sha256", "0" * 64),
        ("observation_ref", "steps/1/after.json"),
        ("observation_ref", "../after.json"),
        ("start", True),
        ("end", 10**9),
    ],
)
def test_forged_operation_binding_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    conduct(tmp_path)
    rewrite(
        tmp_path / "proof/intermediate/operation.json", lambda data: data.update({field: value})
    )
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize("location", ["intermediate_preparation", "first", "second"])
def test_executed_step_cannot_be_reclassified_as_not_started(tmp_path: Path, location: str) -> None:
    conduct(tmp_path)

    def edit(data: dict[str, Any]) -> None:
        step = (
            data[location]
            if location == "intermediate_preparation"
            else data["steps"][location == "second"]
        )
        if location == "intermediate_preparation":
            step.update(stage="not_started", generation=0)
        else:
            step["phase"] = "idle"

    rewrite(tmp_path / "proof/result.json", edit)
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


def test_changed_in_bounds_range_cannot_claim_another_mutation(tmp_path: Path) -> None:
    conduct(tmp_path)
    rewrite(
        tmp_path / "proof/intermediate/operation.json",
        lambda data: data.update(end=data["end"] + 1),
    )
    with pytest.raises(ValueError, match="contradicts"):
        read_evidence(tmp_path / "proof")


def test_failed_first_install_cannot_claim_started_intermediate(tmp_path: Path) -> None:
    conduct(tmp_path, first_wrong=True)

    def edit(data: dict[str, Any]) -> None:
        data["intermediate_preparation"].update(stage="started", generation=1)

    rewrite(tmp_path / "proof/result.json", edit)
    with pytest.raises(ValueError, match="Blocked preparation has incompatible evidence"):
        read_evidence(tmp_path / "proof")


def test_reinstall_expectations_write_failure_replays_incomplete_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter

    original = TestResultWriter.retain

    def interrupted(
        writer: TestResultWriter, artifact: JsonArtifact | SnapshotArtifact
    ) -> ArtifactReceipt:
        if artifact.reference == "intermediate/repair-plan.json":
            raise OSError("Controlled repair expectations archive failure")
        return original(writer, artifact)

    monkeypatch.setattr(TestResultWriter, "retain", interrupted)
    result, installer = conduct(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == "preparation_expectations_retained"
    assert not (tmp_path / "proof/intermediate/before.json").exists()
    assert (tmp_path / "proof/expectations/intermediate.json").is_file()
    assert not (tmp_path / "proof/expectations/reinstall.json").exists()


def test_failed_first_observation_cannot_smuggle_finished_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.container.evidence_writer import TestResultWriter
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    original = EffectEnvironment.observe

    def unavailable(
        environment: EffectEnvironment, writer: TestResultWriter, phase: str, *, step_index: int = 0
    ) -> FilesystemSnapshot:
        if step_index == 0 and phase == "after":
            raise OSError("Controlled first observation failure")
        return original(environment, writer, phase, step_index=step_index)

    monkeypatch.setattr(EffectEnvironment, "observe", unavailable)
    result, _ = conduct(tmp_path)
    assert result.status == "incomplete"

    def forge(data: dict[str, Any]) -> None:
        intermediate = data["intermediate_preparation"]
        intermediate.update(stage="ready", generation=9)

    rewrite(tmp_path / "proof/result.json", forge)
    with pytest.raises(ValueError, match="Blocked preparation has incompatible evidence"):
        read_evidence(tmp_path / "proof")


@pytest.fixture
def altered_proof(tmp_path: Path) -> Path:
    """Reader-owned literal evidence: no producer or expectation builder is run."""
    payload = json.loads(
        (Path(__file__).parents[2] / "fixtures/retained-altered-proof.json").read_text()
    )
    for relative, content in payload.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_altered_replay_from_independent_retained_data(altered_proof: Path) -> None:
    result = read_evidence(altered_proof)
    assert result.status == "passed"
    assert result.case["name"] == "altered-section"


@pytest.mark.parametrize(
    "relative",
    [
        "case.json",
        "intermediate/operation.json",
        "intermediate/repair-plan.json",
        "intermediate/before.json",
        "intermediate/after.json",
        "intermediate/after/project/GUIDE.md",
        "intermediate/verification.json",
        "expectations/intermediate.json",
        "expectations/reinstall.json",
        "expected/instructions.md",
        "steps/1/after.json",
    ],
)
def test_altered_missing_proof_cannot_claim_success(altered_proof: Path, relative: str) -> None:
    (altered_proof / relative).unlink()
    with pytest.raises((ValueError, OSError)):
        read_evidence(altered_proof)


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_sha256", "0" * 64),
        ("document_sha256", "0" * 64),
        ("observation_ref", "steps/1/after.json"),
        ("destination", {"root": "home", "path": "GUIDE.md"}),
        ("start", 0),
        ("end", 10**9),
        ("replacement", "V3JvbmcgYm9keS4K"),
        ("format", "prepared-byte-range-v1"),
    ],
)
def test_altered_forged_operation_is_rejected(
    altered_proof: Path, field: str, value: object
) -> None:
    rewrite(altered_proof / "intermediate/operation.json", lambda data: data.update({field: value}))
    with pytest.raises(ValueError):
        read_evidence(altered_proof)


@pytest.mark.parametrize("artifact", ["case", "content", "observation", "verdict", "expectation"])
def test_altered_forged_evidence_is_rejected(altered_proof: Path, artifact: str) -> None:
    if artifact == "case":
        rewrite(
            altered_proof / "case.json",
            lambda data: data["intermediate_preparation"].update(body="V3JvbmcuCg=="),
        )
    elif artifact == "content":
        (altered_proof / "intermediate/after/project/GUIDE.md").write_text("Wrong observation.\n")
    elif artifact == "observation":
        rewrite(altered_proof / "intermediate/after.json", lambda data: data.update(entries=[]))
    elif artifact == "verdict":
        rewrite(
            altered_proof / "intermediate/verification.json",
            lambda data: data.update(complete=False),
        )
    else:
        rewrite(
            altered_proof / "expectations/intermediate.json",
            lambda data: data["expectations"][0].update(content="V3JvbmcuCg=="),
        )
    with pytest.raises(ValueError):
        read_evidence(altered_proof)


def test_observed_bad_replacement_remains_an_explainable_failure(altered_proof: Path) -> None:
    import shutil

    # The requested operation stays intact; the physical outcome is nonconforming.
    (altered_proof / "intermediate/after/project/GUIDE.md").write_text(
        "## Personal before\nKeep before.\n\n## graphify\nWrong body.\n"
        "## Personal after\nKeep after.\n\n"
    )
    verdict = {
        "complete": True,
        "obstacles": [],
        "mismatches": [
            {
                "type": "content_mismatch",
                "root": "project",
                "path": "GUIDE.md",
                "expected": "bytes identical to retained source",
                "observed": "different bytes",
            }
        ],
    }
    import hashlib

    performed = {
        "format": "performed-mutation-v3",
        "kind": "markdown",
        "operation": json.loads((altered_proof / "intermediate/operation.json").read_text()),
        "document_sha256": hashlib.sha256(
            (altered_proof / "intermediate/after/project/GUIDE.md").read_bytes()
        ).hexdigest(),
    }
    (altered_proof / "intermediate/performed.json").write_text(json.dumps(performed))
    (altered_proof / "intermediate/verification.json").write_text(json.dumps(verdict))

    def fail(data: dict[str, Any]) -> None:
        data["status"] = "failed"
        data["intermediate_preparation"].update(
            stage="verification_retained",
            generation=8,
            reason="Preparation verification failed or incomplete",
        )
        from tools.install_sandbox.contracts.results import StepState

        data["steps"][1] = StepState.idle("install").to_data()

    rewrite(altered_proof / "result.json", fail)
    shutil.rmtree(altered_proof / "steps/1")
    (altered_proof / "expectations/reinstall.json").unlink()
    result = read_evidence(altered_proof)
    assert result.status == "failed" and result.steps[1].phase == "idle"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == "verification_retained"
    assert (
        json.loads((altered_proof / "intermediate/verification.json").read_text())["mismatches"][0][
            "type"
        ]
        == "content_mismatch"
    )


@pytest.mark.parametrize("terminal", ["before", "verification"])
def test_incomplete_terminal_preparation_rejects_next_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment

    original = EffectEnvironment.observe_intermediate

    def obstruct(environment: EffectEnvironment, phase: str):
        observation = original(environment, phase)
        if phase == ("before" if terminal == "before" else "after"):
            if terminal == "before":
                key = next(iter(observation.contents))
                observation.contents[key] += b"external edit"
            else:
                key = next(iter(observation.contents))
                observation.contents.pop(key)
                observation.obstacles.append(
                    {
                        "root": key[0],
                        "path": key[1],
                        "operation": "read_file",
                        "reason": "Controlled unavailable bytes",
                    }
                )
        return observation

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", obstruct)
    result, installer = conduct(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert read_evidence(tmp_path / "proof").status == "incomplete"
    relative = (
        "intermediate/.performed.json.stopped.tmp"
        if terminal == "before"
        else "expectations/.reinstall.json.stopped.tmp"
    )
    (tmp_path / "proof" / relative).write_bytes(b"partial")
    with pytest.raises(ValueError, match="staging"):
        read_evidence(tmp_path / "proof")


@pytest.mark.parametrize("kind", ["file_symlink", "directory_symlink", "fifo", "unknown_directory"])
def test_intermediate_inventory_rejects_unconfined_or_unsupported_entries(
    altered_proof: Path, tmp_path: Path, kind: str
) -> None:
    import os

    candidate = altered_proof / "intermediate/unrecognized"
    if kind == "file_symlink":
        candidate.symlink_to(altered_proof / "case.json")
    elif kind == "directory_symlink":
        candidate.symlink_to(tmp_path.parent, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(candidate)
    else:
        candidate.mkdir()
    with pytest.raises(ValueError):
        read_evidence(altered_proof)


def test_ready_preparation_rejects_leftover_temporary(altered_proof: Path) -> None:
    (altered_proof / "expectations/.reinstall.json.leftover.tmp").write_bytes(b"partial")
    with pytest.raises(ValueError, match="staging"):
        read_evidence(altered_proof)
