"""Archive-only rejection of missing, forged and misclassified transition proofs."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.test_missing_section_run import conduct
from tools.install_sandbox.host.result_reader import read_evidence


def rewrite(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize(
    "relative",
    [
        "intermediate/operation.json",
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
        step["progress"] = "not_started"

    rewrite(tmp_path / "proof/result.json", edit)
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


def test_changed_in_bounds_range_cannot_claim_another_mutation(tmp_path: Path) -> None:
    conduct(tmp_path)
    rewrite(
        tmp_path / "proof/intermediate/operation.json",
        lambda data: data.update(end=data["end"] + 1),
    )
    with pytest.raises(ValueError, match="byte operation"):
        read_evidence(tmp_path / "proof")


def test_failed_first_install_cannot_claim_started_intermediate(tmp_path: Path) -> None:
    conduct(tmp_path, first_wrong=True)

    def edit(data: dict[str, Any]) -> None:
        data["intermediate_preparation"]["progress"] = "incomplete"

    rewrite(tmp_path / "proof/result.json", edit)
    with pytest.raises(ValueError, match="conforming first"):
        read_evidence(tmp_path / "proof")


def test_reinstall_expectations_write_failure_replays_incomplete_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter

    original = TestResultWriter.write_metadata

    def interrupted(writer: TestResultWriter, relative: str, value: object) -> None:
        if relative == "expectations/reinstall.json":
            raise OSError("Controlled repair expectations archive failure")
        original(writer, relative, value)

    monkeypatch.setattr(TestResultWriter, "write_metadata", interrupted)
    result, installer = conduct(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["observations"] == {"before": None, "after": None}
    assert (tmp_path / "proof/expectations/intermediate.json").is_file()
    assert not (tmp_path / "proof/expectations/reinstall.json").exists()


def test_failed_first_observation_cannot_smuggle_finished_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.container.environment import FilesystemSnapshot
    from tools.install_sandbox.container.evidence_writer import TestResultWriter

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
        intermediate["progress"] = "finished"
        intermediate["verification"] = {"complete": True, "mismatches": [], "obstacles": []}

    rewrite(tmp_path / "proof/result.json", forge)
    with pytest.raises(ValueError, match="conforming first"):
        read_evidence(tmp_path / "proof")
