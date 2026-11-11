"""Physical reference repair with a literal installer independent of expectations."""

import json
import shutil
from pathlib import Path
from typing import Literal

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange, write
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence


def _damage_repair(selected: Path, skill: Path, project: Path, fault: str | None) -> None:
    if fault == "absent":
        selected.unlink()
    elif fault == "wrong":
        selected.write_text("Incorrect restoration.\n")
    elif fault == "other-reference":
        (skill / "references/z-last.md").write_text("Unrelated reference changed.\n")
    elif fault == "backup":
        (project / ".synthetic/config.json.graphify-bak").write_text("Changed backup.\n")


def _cleanup(root: Path, subject: Path, case: Path, spec: Path, context: Path) -> None:
    shutil.rmtree(subject)
    shutil.rmtree(root / "work", ignore_errors=True)
    for path in (case, spec, context):
        path.unlink()


def conduct_reference(
    root: Path,
    *,
    skill_root: Literal["home", "project"] = "home",
    other_effects: bool = True,
    multiple: bool = False,
    empty: bool = False,
    first_wrong: bool = False,
    repair_fault: str | None = None,
) -> tuple[InstallTestResult, LiteralInstaller]:
    subject, spec, context = arrange(
        root, skill_root=skill_root, markdown=other_effects, hooks=other_effects
    )
    if empty:
        (subject / "reference-data/nested/reference.md").unlink()
    if multiple:
        write(subject / "reference-data/a/first.md", "First lexical reference.\n")
        write(subject / "reference-data/z-last.md", "Last lexical reference.\n")
    cases = build_effect_cases(
        EffectSpecReader().read(spec).scopes[0].effects, SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in cases.cases if case.name == "missing-reference")
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller(skill_root=skill_root, markdown=other_effects, hooks=other_effects)

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = installer.execute(args, project, environment, timeout)
        target_root = Path(environment["HOME"]) if skill_root == "home" else project
        skill = target_root / ".synthetic/skills/package"
        selected = skill / "references" / ("a/first.md" if multiple else "nested/reference.md")
        if multiple:
            write(skill / "references/a/first.md", "First lexical reference.\n")
            write(skill / "references/z-last.md", "Last lexical reference.\n")
        if len(installer.calls) == 1 and first_wrong:
            selected.write_text("Invalid first installation.\n")
        if len(installer.calls) == 2:
            _damage_repair(selected, skill, project, repair_fault)
        return result

    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=case_file,
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    _cleanup(root, subject, case_file, spec, context)
    assert read_evidence(root / "proof") == result
    return result, installer


@pytest.mark.parametrize("skill_root", ["home", "project"])
@pytest.mark.parametrize("other_effects", [False, True])
@pytest.mark.parametrize("multiple", [False, True])
def test_reference_is_restored_and_replays_after_cleanup(
    tmp_path: Path, skill_root: Literal["home", "project"], other_effects: bool, multiple: bool
) -> None:
    result, installer = conduct_reference(
        tmp_path, skill_root=skill_root, other_effects=other_effects, multiple=multiple
    )
    assert result.status == "passed" and len(installer.calls) == 2
    operation = json.loads((tmp_path / "proof/intermediate/operation.json").read_text())
    assert operation["destination"] == {
        "root": skill_root,
        "path": ".synthetic/skills/package/references/"
        + ("a/first.md" if multiple else "nested/reference.md"),
    }
    assert operation["observation_ref"] == "steps/0/after.json"


def test_empty_bundle_stops_before_installer(tmp_path: Path) -> None:
    result, installer = conduct_reference(tmp_path, empty=True)
    assert result.status == "not_run" and not installer.calls
    assert result.preparation.checkpoint == "stopped"
    assert result.preparation.stop is not None
    assert result.preparation.stop.category == "validation"


def test_bad_initial_install_blocks_reference_removal(tmp_path: Path) -> None:
    result, installer = conduct_reference(tmp_path, first_wrong=True)
    assert result.status == "failed" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
    assert not (tmp_path / "proof/intermediate/operation.json").exists()


@pytest.mark.parametrize("fault", ["absent", "wrong", "other-reference", "backup"])
def test_success_exit_does_not_hide_failed_reference_restoration(
    tmp_path: Path, fault: str
) -> None:
    result, installer = conduct_reference(tmp_path, multiple=True, repair_fault=fault)
    assert result.status == "failed" and len(installer.calls) == 2
    verification = result.steps[1].verification
    assert verification is not None and verification.complete and verification.mismatches


@pytest.mark.parametrize("fault", ["changed-before", "extra-removal", "no-removal"])
def test_reference_removal_requires_exact_observed_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    original = EffectEnvironment.observe_intermediate

    def observe(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
        references = environment.home / ".synthetic/skills/package/references"
        if phase == "before" and fault == "changed-before":
            (references / "a/first.md").write_text("Changed since validation.\n")
        if phase == "after":
            if fault == "extra-removal":
                (references / "z-last.md").unlink()
            elif fault == "no-removal":
                write(references / "a/first.md", "First lexical reference.\n")
        return original(environment, phase)

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", observe)
    result, installer = conduct_reference(tmp_path, multiple=True)
    assert result.status in {"failed", "incomplete"} and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"


def test_incomplete_reference_inventory_stops_before_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = EffectEnvironment.capture_sources

    def incomplete(environment: EffectEnvironment, subject: Path) -> FilesystemSnapshot:
        snapshot = original(environment, subject)
        snapshot.contents.pop(("subject", "reference-data/nested/reference.md"))
        snapshot.obstacles.append(
            {
                "root": "subject",
                "path": "reference-data/nested/reference.md",
                "operation": "read_file",
                "reason": "Controlled incomplete source observation",
            }
        )
        return snapshot

    monkeypatch.setattr(EffectEnvironment, "capture_sources", incomplete)
    result, installer = conduct_reference(tmp_path)
    assert result.status == "not_run" and not installer.calls
    assert result.preparation.checkpoint == "stopped"
    assert result.preparation.stop is not None
    assert result.preparation.stop.category == "validation"


@pytest.mark.parametrize("wrong", ["root", "path"])
def test_physical_removal_rejects_another_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong: str
) -> None:
    from dataclasses import replace

    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.contracts.bound_mutation import BoundFileRemoval, BoundMutation
    from tools.install_sandbox.contracts.effects import Destination

    original = intermediate_execution.apply_mutation

    def redirected(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        assert isinstance(operation, BoundFileRemoval)
        destination = Destination(
            "project" if wrong == "root" else operation.destination.root,
            operation.destination.path if wrong == "root" else ".synthetic/skills/package/SKILL.md",
        )
        original(
            replace(operation, destination=destination),
            environment,
            case_bytes,
            first_after,
            sources,
        )

    monkeypatch.setattr(intermediate_execution, "apply_mutation", redirected)
    result, installer = conduct_reference(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"


@pytest.mark.parametrize("fault", ["changed", "symlink-file", "symlink-parent", "skip"])
def test_physical_adapter_checks_current_file_before_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.contracts.bound_mutation import BoundFileRemoval, BoundMutation

    original = intermediate_execution.apply_mutation

    def interfere(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        assert isinstance(operation, BoundFileRemoval)
        target = environment.home / operation.destination.path
        if fault == "skip":
            return
        if fault == "changed":
            target.write_text("Changed after before observation.\n")
        elif fault == "symlink-file":
            target.unlink()
            target.symlink_to(target.parents[2] / "SKILL.md")
        else:
            moved = target.parent.with_name("moved-nested")
            target.parent.rename(moved)
            target.parent.symlink_to(moved, target_is_directory=True)
        original(operation, environment, case_bytes, first_after, sources)
        pytest.fail("Adapter accepted an unsafe physical reference")

    monkeypatch.setattr(intermediate_execution, "apply_mutation", interfere)
    result, installer = conduct_reference(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
