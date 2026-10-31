"""Honest nonconforming preparation becomes failed at its durable checkpoint."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.results import CheckpointReceipt
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence
from tools.install_sandbox.rules.repair_protocol import RepairSession


class ProcessStopped(BaseException):
    """Process loss bypasses normal error handling and finalization."""


def publication_target(relative: str, value: object) -> str | None:
    if relative == "intermediate/verification.json":
        return "verdict"
    if relative != "result.json":
        return None
    checkpoint = cast(dict[str, Any], value).get("intermediate_preparation")
    if checkpoint and checkpoint["stage"] == "verification_retained":
        return "checkpoint"
    return None


def inject_failure_and_stop(patches: pytest.MonkeyPatch, window: str) -> None:
    observe = EffectEnvironment.observe_intermediate
    publish = cast(Callable[[Writer, str, object], None], vars(Writer)["_write_json"])
    confirm = RepairSession.confirm_checkpoint

    def nonconforming(environment: EffectEnvironment, writer: Writer, phase: str):
        if phase == "after":
            (environment.project / "foreign-file").write_bytes(b"Unexpected preparation effect.\n")
        return observe(environment, writer, phase)

    def publish_at_window(writer: Writer, relative: str, value: object) -> None:
        target = publication_target(relative, value)
        if window == f"before-{target}":
            raise ProcessStopped()
        publish(writer, relative, value)
        if window == f"after-{target}":
            raise ProcessStopped()

    def confirm_at_window(session: RepairSession, receipt: CheckpointReceipt) -> None:
        pending = session.pending
        confirm(session, receipt)
        if (
            window == "after-confirm"
            and pending
            and pending.checkpoint["stage"] == "verification_retained"
        ):
            raise ProcessStopped()

    patches.setattr(EffectEnvironment, "observe_intermediate", nonconforming)
    patches.setattr(Writer, "_write_json", publish_at_window)
    patches.setattr(RepairSession, "confirm_checkpoint", confirm_at_window)


def assert_no_dependent_effects(proof: Path, window: str) -> None:
    assert not (proof / "expectations/reinstall.json").exists()
    saved = json.loads((proof / "result.json").read_text())
    assert saved["steps"][1]["progress"] == "not_started"
    assert saved["steps"][1]["command"] is None
    assert not (proof / "steps/1").exists()
    if window != "before-verdict":
        verdict = json.loads((proof / "intermediate/verification.json").read_text())
        assert verdict["complete"] is True
        assert verdict["mismatches"]
        assert verdict["obstacles"] == []


def failed_archive(
    root: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, window: str
) -> Path:
    subject, spec, context = arrange(root)
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    ).cases
    case_file = root / "case.json"
    next(case for case in cases if case.name == scenario).write(case_file)
    installer = LiteralInstaller()
    runner = InstallTestRunner(InstallerDriver(installer.execute))
    kwargs = dict(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=case_file,
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    with monkeypatch.context() as patches:
        inject_failure_and_stop(patches, window)
        if window == "uninterrupted":
            assert runner.run_case(**kwargs).status == "failed"
        else:
            with pytest.raises(ProcessStopped):
                runner.run_case(**kwargs)
    assert len(installer.calls) == 1
    proof = root / "proof"
    assert_no_dependent_effects(proof, window)
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    for live_input in (case_file, spec, context):
        live_input.unlink()
    return proof


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize(
    ("window", "expected"),
    [
        ("before-verdict", "incomplete"),
        ("after-verdict", "incomplete"),
        ("before-checkpoint", "incomplete"),
        ("after-checkpoint", "failed"),
        ("after-confirm", "failed"),
        ("uninterrupted", "failed"),
    ],
)
def test_failed_preparation_replays_at_its_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, window: str, expected: str
) -> None:
    proof = failed_archive(tmp_path, monkeypatch, scenario, window)
    saved = json.loads((proof / "result.json").read_text())
    assert read_evidence(proof).status == expected
    assert saved["status"] == expected


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize("window", ["after-verdict", "after-checkpoint"])
@pytest.mark.parametrize("tamper", ["verdict", "checkpoint", "status", "expectations"])
def test_failed_preparation_rejects_contradictory_retained_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, window: str, tamper: str
) -> None:
    proof = failed_archive(tmp_path, monkeypatch, scenario, window)
    relative = {
        "verdict": "intermediate/verification.json",
        "checkpoint": "result.json",
        "status": "result.json",
        "expectations": "expectations/intermediate.json",
    }[tamper]
    path = proof / relative
    data = json.loads(path.read_text())
    if tamper == "verdict":
        data["mismatches"] = []
    elif tamper == "checkpoint":
        data["intermediate_preparation"]["reason"] = "Forged checkpoint diagnostic"
    elif tamper == "status":
        # Deliberately contradict the durable, complete nonconforming checkpoint.
        data["status"] = "passed"
    else:
        # Substitute a real but different retained expectation set.
        data = json.loads((proof / "intermediate/repair-plan.json").read_text())
    path.write_text(json.dumps(data))
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)
