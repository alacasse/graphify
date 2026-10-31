"""Controlled installer counterexamples for the native altered-section journey."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.rules.repair_scenario import PreparationPlan, MarkdownRepairScenario
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence

# Literal outputs are deliberately independent from both builder fragments and its slice.
BEFORE = "## Personal before\nKeep before.\n\n"
AFTER = "## Personal after\nKeep after.\n\n"
SECTION = "## graphify\nConsult the synthetic map.\n"


def conduct(
    root: Path,
    *,
    repair: str | None = None,
    first_wrong: bool = False,
    foreign: bool = False,
    changed_effect: str | None = None,
):
    subject, spec, context = arrange(root)
    built = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in built.cases if case.name == "altered-section")
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
            paths = {
                "skill": Path(environment["HOME"]) / ".synthetic/skills/package/SKILL.md",
                "backup": project / ".synthetic/config.json.graphify-bak",
                "hooks": project / ".synthetic/config.json",
            }
            if changed_effect is not None:
                paths[changed_effect].write_text("Changed effect.\n")
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


def test_first_install_failure_blocks_preparation_and_repair(tmp_path: Path) -> None:
    result, installer = conduct(tmp_path, first_wrong=True)
    assert result.status == "failed" and len(installer.calls) == 1
    assert result.steps[1]["progress"] == "not_started"
    assert result.intermediate_preparation is not None
    assert result.intermediate_preparation["stage"] == "not_started"


def damage_observation(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    observe = EffectEnvironment.observe_intermediate

    def unavailable(
        environment: EffectEnvironment, writer: TestResultWriter, phase: str
    ) -> FilesystemSnapshot:
        if failure == "unobservable" and phase == "after":
            raise OSError("Controlled missing observation")
        if failure == "changed" and phase == "before":
            (environment.project / "GUIDE.md").write_text(BEFORE + AFTER)
        if failure == "foreign" and phase == "after":
            (environment.project / "foreign-file").write_text("Foreign preparation change.\n")
        return observe(environment, writer, phase)

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", unavailable)


def damaged_operation(operation: BoundMarkdownMutation, failure: str) -> BoundMarkdownMutation:
    from dataclasses import replace

    if failure == "wrong-range":
        return replace(operation, end=operation.end + 1)
    if failure == "heading":
        return replace(operation, start=operation.start - 1)
    replacement = (
        b"Consult the synthetic map.\n" if failure == "unchanged" else b"Wrong replacement.\n"
    )
    return replace(operation, replacement=replacement)


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-range",
        "partial",
        "unobservable",
        "changed",
        "wrong-body",
        "heading",
        "foreign",
        "unchanged",
    ],
)
def test_failed_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from dataclasses import replace

    from tools.install_sandbox.container import intermediate_execution as transition

    if failure in {"wrong-range", "wrong-body", "heading", "unchanged"}:
        original = MarkdownRepairScenario.bind

        def wrong_range(
            self: MarkdownRepairScenario,
            first_after: FilesystemSnapshot,
            observation_ref: str,
            validation: VerificationResult,
            installed: ExpectationSet,
            case_bytes: bytes,
        ) -> PreparationPlan:
            plan = original(self, first_after, observation_ref, validation, installed, case_bytes)
            assert isinstance(plan, PreparationPlan)
            return replace(plan, operation=damaged_operation(plan.operation, failure))

        monkeypatch.setattr(MarkdownRepairScenario, "bind", wrong_range)
    elif failure == "partial":

        def partial(
            operation: BoundMarkdownMutation,
            environment: EffectEnvironment,
            case_bytes: bytes,
            first_after: FilesystemSnapshot,
        ) -> None:
            # The durable intent must precede even a partially successful mutation.
            saved = json.loads((tmp_path / "proof/result.json").read_text())
            assert saved["intermediate_preparation"]["stage"] == "before_retained"
            (environment.project / "GUIDE.md").write_text(BEFORE)
            raise OSError("Controlled partial mutation")

        monkeypatch.setattr(transition, "apply_markdown_mutation", partial)
    else:
        damage_observation(monkeypatch, failure)

    result, installer = conduct(tmp_path)
    assert len(installer.calls) == 1
    assert result.status == (
        "failed"
        if failure in {"wrong-range", "wrong-body", "heading", "foreign", "unchanged"}
        else "incomplete"
    )
    assert result.steps[1]["progress"] == "not_started"
    record = result.intermediate_preparation
    assert record is not None
    assert record["stage"] == (
        "verification_retained"
        if failure in {"wrong-range", "wrong-body", "heading", "foreign", "unchanged"}
        else {
            "partial": "before_retained",
            "unobservable": "mutation_recorded",
            "changed": "before_retained",
        }[failure]
    )


@pytest.mark.parametrize("changed_effect", ["skill", "hooks", "backup"])
def test_repair_preserves_other_effects_and_initial_backup(
    tmp_path: Path, changed_effect: str
) -> None:
    result, installer = conduct(tmp_path, changed_effect=changed_effect)
    assert result.status == "failed"
    assert len(installer.calls) == 2
    verification = result.steps[1]["verification"]
    assert verification is not None and verification.complete and verification.mismatches
