"""Controlled installer counterexamples for the native missing-section journey."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.intermediate_builder import PreparationPlan
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.intermediate import PreparedByteRange
from tools.install_sandbox.contracts.results import InstallTestResult, VerificationResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence

# Literal outputs are deliberately independent from both builder fragments and its slice.
BEFORE = "## Personal before\nKeep before.\n\n"
AFTER = "## Personal after\nKeep after.\n\n"
SECTION = "## graphify\nConsult the synthetic map.\n"


def conduct(
    root: Path, *, repair: str | None = None, first_wrong: bool = False, foreign: bool = False
):
    subject, spec, context = arrange(root)
    built = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in built.cases if case.name == "missing-section")
    case_file = root / "case.json"
    case.write(case_file)
    original_case = case_file.read_bytes()
    installer = LiteralInstaller()

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = installer.execute(args, project, environment, timeout)
        if len(installer.calls) == 1 and first_wrong:
            (project / "GUIDE.md").write_text(BEFORE + "## graphify\nWrong.\n" + AFTER)
        if len(installer.calls) == 2:
            if repair is not None:
                (project / "GUIDE.md").write_text(repair)
            if foreign:
                (project / "foreign-file").write_text("Unexpected effect.\n")
        return result

    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=case_file,
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    assert case_file.read_bytes() == original_case
    assert (root / "proof/case.json").read_bytes() == original_case
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    case_file.unlink()
    spec.unlink()
    context.unlink()
    assert read_evidence(root / "proof") == result
    return result, installer


@pytest.mark.parametrize(
    "repair", [SECTION + BEFORE + AFTER, BEFORE + SECTION + AFTER, BEFORE + AFTER + SECTION]
)
def test_repair_accepts_each_section_position_after_cleanup(tmp_path: Path, repair: str) -> None:
    result, installer = conduct(tmp_path, repair=repair)
    assert result.status == "passed"
    assert len(installer.calls) == 2


@pytest.mark.parametrize(
    "repair",
    [
        BEFORE + AFTER,
        BEFORE + AFTER + SECTION + SECTION,
        BEFORE + AFTER + "## graphify\nWrong.\n",
        AFTER + BEFORE + SECTION,
        BEFORE.replace("Keep before.", "Changed before.") + AFTER + SECTION,
        AFTER + SECTION,
    ],
)
def test_invalid_repair_is_observed_failure(tmp_path: Path, repair: str) -> None:
    result, installer = conduct(tmp_path, repair=repair)
    assert result.status == "failed"
    assert len(installer.calls) == 2
    verification = result.steps[1]["verification"]
    assert verification is not None and verification.complete and verification.mismatches


def test_foreign_effect_during_repair_fails(tmp_path: Path) -> None:
    result, installer = conduct(tmp_path, foreign=True)
    assert result.status == "failed" and len(installer.calls) == 2


def test_first_install_failure_blocks_removal_and_repair(tmp_path: Path) -> None:
    result, installer = conduct(tmp_path, first_wrong=True)
    assert result.status == "failed" and len(installer.calls) == 1
    assert result.steps[1]["progress"] == "not_started"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["progress"] == "not_started"


@pytest.mark.parametrize("failure", ["wrong-range", "partial", "unobservable", "changed"])
def test_failed_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from dataclasses import replace

    from tools.install_sandbox.container import intermediate_execution as transition

    if failure == "wrong-range":
        original = transition.prepare_intermediate

        def wrong_range(
            case: EffectInstallCase,
            sources: FilesystemSnapshot,
            first_after: FilesystemSnapshot,
            observation_ref: str,
            validation: VerificationResult,
            installed: ExpectationSet,
            case_bytes: bytes,
        ) -> PreparationPlan:
            plan = original(
                case, sources, first_after, observation_ref, validation, installed, case_bytes
            )
            assert isinstance(plan, PreparationPlan)
            return replace(plan, operation=replace(plan.operation, end=plan.operation.end + 1))

        monkeypatch.setattr(transition, "prepare_intermediate", wrong_range)
    elif failure == "partial":

        def partial(
            environment: EffectEnvironment,
            operation: PreparedByteRange,
            case_bytes: bytes,
            first_after: FilesystemSnapshot,
        ) -> None:
            # The durable intent must precede even a partially successful mutation.
            saved = json.loads((tmp_path / "proof/result.json").read_text())
            assert saved["intermediate_preparation"]["progress"] == "incomplete"
            (environment.project / "GUIDE.md").write_text(BEFORE)
            raise OSError("Controlled partial mutation")

        monkeypatch.setattr(transition, "apply_prepared_range", partial)
    else:
        observe = EffectEnvironment.observe_intermediate

        def unavailable(
            environment: EffectEnvironment, writer: TestResultWriter, phase: str
        ) -> FilesystemSnapshot:
            if failure == "unobservable" and phase == "after":
                raise OSError("Controlled missing observation")
            if failure == "changed" and phase == "before":
                (environment.project / "GUIDE.md").write_text(BEFORE + AFTER)
            return observe(environment, writer, phase)

        monkeypatch.setattr(EffectEnvironment, "observe_intermediate", unavailable)

    result, installer = conduct(tmp_path)
    assert len(installer.calls) == 1
    assert result.status == ("failed" if failure == "wrong-range" else "incomplete")
    assert result.steps[1]["progress"] == "not_started"
    record = result.intermediate_preparation
    assert record is not None
    assert record["progress"] == ("finished" if failure == "wrong-range" else "incomplete")


def test_simple_reinstall_rejects_unexplained_intermediate_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.install_sandbox.component.container.test_native_integration import prepared, run

    prepared(tmp_path)
    observe = EffectEnvironment.observe

    def change_before_observation(
        environment: EffectEnvironment, writer: TestResultWriter, phase: str, *, step_index: int = 0
    ) -> FilesystemSnapshot:
        if phase == "before" and step_index == 1:
            (environment.project / "GUIDE.md").write_text("Unexpected intermediate replacement.\n")
        return observe(environment, writer, phase, step_index=step_index)

    monkeypatch.setattr(EffectEnvironment, "observe", change_before_observation)
    installer = LiteralInstaller()
    result = run(tmp_path, InstallerDriver(installer.execute))
    assert result.status != "passed" and len(installer.calls) == 1
    assert result.intermediate_preparation is None
    assert result.steps[1]["progress"] == "incomplete"
    shutil.rmtree(tmp_path / "subject")
    shutil.rmtree(tmp_path / "work")
    assert read_evidence(tmp_path / "proof") == result


def test_unpersisted_preparation_intent_prevents_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.contracts.results import EvidenceWriteError

    subject, spec, context = arrange(tmp_path)
    case = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    ).cases[1]
    case.write(tmp_path / "case.json")
    write_result = TestResultWriter.write_result

    def cannot_persist(writer: TestResultWriter, result: InstallTestResult) -> None:
        record = result.intermediate_preparation
        if record is not None and record["progress"] == "incomplete":
            raise EvidenceWriteError("Controlled intent persistence failure")
        write_result(writer, result)

    monkeypatch.setattr(TestResultWriter, "write_result", cannot_persist)
    installer = LiteralInstaller()
    with pytest.raises(EvidenceWriteError, match="intent persistence"):
        InstallTestRunner(InstallerDriver(installer.execute)).run_case(
            reference_sources=subject,
            prepared_executable=tmp_path / "controlled-executable",
            case_file=tmp_path / "case.json",
            work_directory=tmp_path / "work",
            output_directory=tmp_path / "proof",
        )
    assert len(installer.calls) == 1
    assert (tmp_path / "work/environment/project/GUIDE.md").read_text() == BEFORE + SECTION + AFTER
    assert not (tmp_path / "proof/intermediate/operation.json").exists()
    saved = json.loads((tmp_path / "proof/result.json").read_text())
    assert saved["intermediate_preparation"]["progress"] == "not_started"


@pytest.mark.parametrize("obstructed", [False, True])
def test_removal_rejects_foreign_changes_and_incomplete_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, obstructed: bool
) -> None:
    observe = EffectEnvironment.observe_intermediate

    def altered(
        environment: EffectEnvironment, writer: TestResultWriter, phase: str
    ) -> FilesystemSnapshot:
        if phase == "after" and not obstructed:
            (environment.project / "foreign-file").write_bytes(b"Unrelated change during removal")
        snapshot = observe(environment, writer, phase)
        if phase == "after" and obstructed:
            snapshot.obstacles.append(
                {
                    "operation": "read_file",
                    "root": "project",
                    "path": "GUIDE.md",
                    "reason": "Controlled observation obstacle",
                }
            )
            writer.write_intermediate_snapshot(snapshot, phase)
        return snapshot

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", altered)
    result, installer = conduct(tmp_path)
    assert len(installer.calls) == 1
    assert result.status == ("incomplete" if obstructed else "failed")
    assert result.steps[1]["progress"] == "not_started"
    preparation = result.intermediate_preparation
    assert preparation is not None and preparation["verification"] is not None
    assert preparation["verification"].complete is not obstructed
