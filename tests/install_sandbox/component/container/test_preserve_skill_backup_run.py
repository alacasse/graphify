"""Backup preservation with a literal installer independent of expectations."""

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
    backup = selected.with_name("SKILL.md.bak")
    if fault in {"absent", "missing-backup"}:
        (selected if fault == "absent" else backup).unlink()
    elif fault is not None:
        changes = {
            "wrong": (selected, b"Incorrect restoration.\n"),
            "other-reference": (skill / "references/z-last.md", b"Unrelated reference changed.\n"),
            "skill-backup": (backup, b"Incorrect backup.\n"),
            "partial-backup": (backup, b"Sandbox previous backup witness.\n"),
            "canonical-backup": (backup, selected.read_bytes()),
            "backup": (project / ".synthetic/config.json.graphify-bak", b"Changed backup.\n"),
        }
        target, content = changes[fault]
        target.write_bytes(content)


def _cleanup(root: Path, subject: Path, case: Path, spec: Path, context: Path) -> None:
    shutil.rmtree(subject)
    shutil.rmtree(root / "work", ignore_errors=True)
    for path in (case, spec, context):
        path.unlink()


def _prepare_reference_sources(
    subject: Path,
    spec: Path,
    empty: bool,
    multiple: bool,
    content: bytes | None,
    markdown_count: int | None,
) -> None:
    if empty:
        (subject / "reference-data/nested/reference.md").unlink()
    if multiple:
        write(subject / "reference-data/a/first.md", "First lexical reference.\n")
        write(subject / "reference-data/z-last.md", "Last lexical reference.\n")
    source = subject / ("package.md")
    if content is not None:
        source.write_bytes(content)
    if markdown_count == 2:
        import yaml

        raw = yaml.safe_load(spec.read_text())
        markdown = next(effect for effect in raw["scopes"]["project"] if effect["family"] == "markdown-section")
        from copy import deepcopy

        second = deepcopy(markdown)
        second["path"] = "OTHER.md"
        second["effect_id"] = "other-instructions"
        raw["scopes"]["project"].append(second)
        spec.write_text(yaml.safe_dump(raw))


def _finish_literal_install(
    installer: LiteralInstaller,
    project: Path,
    environment: dict[str, str],
    skill_root: Literal["home", "project"],
    multiple: bool,
    content: bytes | None,
    markdown_count: int | None,
    first_wrong: bool,
    repair_fault: str | None,
) -> None:
    target_root = Path(environment["HOME"]) if skill_root == "home" else project
    skill = target_root / ".synthetic/skills/package"
    selected = skill / "SKILL.md"
    if multiple:
        write(skill / "references/a/first.md", "First lexical reference.\n")
        write(skill / "references/z-last.md", "Last lexical reference.\n")
    if content is not None:
        selected.write_bytes(content)
    if markdown_count == 2:
        other = project / "OTHER.md"
        text = other.read_text()
        if "## graphify" not in text:
            other.write_text(text + "\n## graphify\nConsult the synthetic map.\n")
    if len(installer.calls) == 1 and first_wrong:
        selected.write_text("Invalid first installation.\n")
    if len(installer.calls) == 2:
        _damage_repair(selected, skill, project, repair_fault)


def conduct_preserve_skill_backup(
    root: Path,
    *,
    skill_root: Literal["home", "project"] = "home",
    other_effects: bool = True,
    multiple: bool = False,
    empty: bool = False,
    content: bytes | None = None,
    markdown_count: int | None = None,
    first_wrong: bool = False,
    first_backup: bool = False,
    repair_fault: str | None = None,
) -> tuple[InstallTestResult, LiteralInstaller]:
    subject, spec, context = arrange(
        root, skill_root=skill_root, markdown=other_effects, hooks=other_effects
    )
    _prepare_reference_sources(subject, spec, empty, multiple, content, markdown_count)
    cases = build_effect_cases(
        EffectSpecReader().read(spec).scopes[0].effects, SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in cases.cases if case.name == "preserve-skill-backup")
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller(skill_root=skill_root, markdown=other_effects, hooks=other_effects)

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        target_root = Path(environment["HOME"]) if skill_root == "home" else project
        selected = target_root / ".synthetic/skills/package/SKILL.md"
        backup = selected.with_name("SKILL.md.bak")
        prior_backup = backup.read_bytes() if backup.exists() else None
        result = installer.execute(args, project, environment, timeout)
        if content is not None and prior_backup is not None:
            # The shared literal installer knows only its default canonical bytes.
            # Preserve the actual prior backup while substituting this test source.
            backup.write_bytes(prior_backup)
        if len(installer.calls) == 1 and first_backup:
            selected.with_name("SKILL.md.bak").write_bytes(b"Unexpected initial backup\n")
        _finish_literal_install(
            installer,
            project,
            environment,
            skill_root,
            multiple,
            content,
            markdown_count,
            first_wrong,
            repair_fault,
        )
        if empty:
            (selected.parent / "references/nested/reference.md").unlink()
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
def test_preserve_skill_backup_is_preserved_and_replays_after_cleanup(
    tmp_path: Path, skill_root: Literal["home", "project"], other_effects: bool, multiple: bool
) -> None:
    result, installer = conduct_preserve_skill_backup(
        tmp_path, skill_root=skill_root, other_effects=other_effects, multiple=multiple
    )
    assert result.status == "passed" and len(installer.calls) == 2
    assert installer.calls[0] == installer.calls[1]
    operation = json.loads((tmp_path / "proof/intermediate/operation.json").read_text())
    assert operation["destination"] == {
        "root": skill_root,
        "path": ".synthetic/skills/package/SKILL.md.bak",
    }
    assert operation["observation_ref"] == "steps/0/after.json"


def test_bad_initial_install_blocks_backup_creation(tmp_path: Path) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, first_wrong=True)
    assert result.status == "failed" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
    assert not (tmp_path / "proof/intermediate/operation.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "absent",
        "wrong",
        "other-reference",
        "backup",
        "skill-backup",
        "missing-backup",
        "partial-backup",
        "canonical-backup",
    ],
)
def test_success_exit_does_not_hide_failed_skill_restoration(tmp_path: Path, fault: str) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, multiple=True, repair_fault=fault)
    assert result.status == "failed" and len(installer.calls) == 2
    verification = result.steps[1].verification
    assert verification is not None and verification.complete and verification.mismatches


def _damage_preparation(environment: EffectEnvironment, phase: str, fault: str) -> None:
    references = environment.home / ".synthetic/skills/package/references"
    if phase == "before" and fault == "changed-before":
        (references.parent / "SKILL.md.bak").write_text("Changed since validation.\n")
    if phase == "after":
        if fault == "extra-removal":
            (references / "z-last.md").unlink()
        elif fault == "extra-change":
            (references / "z-last.md").write_text("Unexpected change")


@pytest.mark.parametrize(
    "fault",
    [
        "changed-before",
        "extra-removal",
        "no-append",
        "double-append",
        "wrong-append",
        "truncated",
        "extra-change",
    ],
)
def test_backup_creation_requires_exact_observed_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    original = EffectEnvironment.observe_intermediate

    def observe(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
        _damage_preparation(environment, phase, fault)
        return original(environment, phase)

    if fault in {"no-append", "double-append", "wrong-append", "truncated"}:
        from tools.install_sandbox.container import intermediate_execution
        from tools.install_sandbox.contracts.bound_mutation import BoundMutation

        apply = intermediate_execution.apply_mutation

        def mutate(
            operation: BoundMutation,
            environment: EffectEnvironment,
            case_bytes: bytes,
            first_after: FilesystemSnapshot,
            sources: FilesystemSnapshot,
        ) -> None:
            target = environment.home / operation.destination.path
            if fault == "no-append":
                return
            apply(operation, environment, case_bytes, first_after, sources)
            if fault == "truncated":
                target.write_bytes(b"Partial backup")
                return
            with target.open("ab") as stream:
                stream.write(
                    b"\nSandbox previous backup witness.\n"
                    if fault == "double-append"
                    else b"Wrong suffix"
                )

        monkeypatch.setattr(intermediate_execution, "apply_mutation", mutate)
    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", observe)
    result, installer = conduct_preserve_skill_backup(tmp_path, multiple=True)
    assert result.status == ("incomplete" if fault == "changed-before" else "failed")
    assert len(installer.calls) == 1
    assert result.steps[1].phase == "idle"


@pytest.mark.parametrize("wrong", ["root", "path", "content"])
def test_physical_creation_rejects_another_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong: str
) -> None:
    from dataclasses import replace

    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.contracts.bound_mutation import BoundFileCreation, BoundMutation
    from tools.install_sandbox.contracts.effects import Destination

    original = intermediate_execution.apply_mutation

    def redirected(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        assert isinstance(operation, BoundFileCreation)
        if wrong == "content":
            original(
                replace(operation, content=b"Unexpected content"),
                environment,
                case_bytes,
                first_after,
                sources,
            )
            return
        destination = Destination(
            "project" if wrong == "root" else operation.destination.root,
            operation.destination.path
            if wrong == "root"
            else ".synthetic/skills/package/references/nested/reference.md",
        )
        original(
            replace(operation, destination=destination),
            environment,
            case_bytes,
            first_after,
            sources,
        )

    monkeypatch.setattr(intermediate_execution, "apply_mutation", redirected)
    result, installer = conduct_preserve_skill_backup(tmp_path)
    assert result.status == "incomplete" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"


def _create_backup_collision(target: Path, fault: str) -> None:
    if fault == "changed":
        target.write_text("Changed after before observation.\n")
    elif fault == "directory":
        target.mkdir()
    elif fault == "symlink-file":
        target.symlink_to(target.parent / ".graphify_version")
    else:
        moved = target.parent.with_name("moved-package")
        target.parent.rename(moved)
        target.parent.symlink_to(moved, target_is_directory=True)


@pytest.mark.parametrize(
    "fault", ["changed", "directory", "symlink-file", "symlink-parent", "skip"]
)
def test_physical_adapter_rejects_creation_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.contracts.bound_mutation import BoundFileCreation, BoundMutation

    original = intermediate_execution.apply_mutation

    def interfere(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        assert isinstance(operation, BoundFileCreation)
        target = environment.home / operation.destination.path
        if fault == "skip":
            return
        _create_backup_collision(target, fault)
        try:
            original(operation, environment, case_bytes, first_after, sources)
        finally:
            if fault == "changed":
                assert target.read_bytes() == b"Changed after before observation.\n"
            elif fault == "symlink-file":
                assert target.is_symlink()
                assert (target.parent / ".graphify_version").read_bytes() == b"8.7.6"
        pytest.fail("Adapter accepted an unsafe physical skill")

    monkeypatch.setattr(intermediate_execution, "apply_mutation", interfere)
    result, installer = conduct_preserve_skill_backup(tmp_path)
    assert result.status == ("failed" if fault == "skip" else "incomplete")
    assert len(installer.calls) == 1 and result.steps[1].phase == "idle"


@pytest.mark.parametrize(
    "content", [b"", b"\x00\xffbinary\n", b"Original\nSandbox previous backup witness.\n"]
)
def test_backup_creation_supports_empty_binary_and_existing_witness(
    tmp_path: Path, content: bytes
) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, content=content)
    assert result.status == "passed" and len(installer.calls) == 2
    archive = tmp_path / "proof/steps/1/after/home/.synthetic/skills/package"
    assert (archive / "SKILL.md").read_bytes() == content
    assert (archive / "SKILL.md.bak").read_bytes() == (
        content + b"\nSandbox previous backup witness.\n"
    )


def test_preserve_skill_backup_with_multiple_markdown_effects(tmp_path: Path) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, markdown_count=2)
    assert result.status == "passed" and len(installer.calls) == 2


@pytest.mark.parametrize("phase", ["preparation", "repair"])
@pytest.mark.parametrize(
    "fault", ["reference", "version", "lock", "personal", "markdown", "hooks", "backup"]
)
def test_preserve_skill_backup_preserves_other_observed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, fault: str
) -> None:
    def damage(home: Path, project: Path) -> None:
        skill = home / ".synthetic/skills/package"
        targets = {
            "reference": skill / "references/nested/reference.md",
            "version": skill / ".graphify_version",
            "lock": next((home / ".cache/graphify/skill-locks").glob("*.lock")),
            "personal": project / "personal-effect-1.txt",
            "markdown": project / "GUIDE.md",
            "hooks": project / ".synthetic/config.json",
            "backup": project / ".synthetic/config.json.graphify-bak",
        }
        target = targets[fault]
        if fault == "reference":
            target.unlink()
            target.mkdir()
        else:
            target.write_bytes(b"Unexpected mutation\n")

    if phase == "preparation":
        original = EffectEnvironment.observe_intermediate

        def observe(environment: EffectEnvironment, observation: str) -> FilesystemSnapshot:
            if observation == "after":
                damage(environment.home, environment.project)
            return original(environment, observation)

        monkeypatch.setattr(EffectEnvironment, "observe_intermediate", observe)
    else:
        execute = LiteralInstaller.execute

        def install(
            installer: LiteralInstaller,
            args: list[str],
            project: Path,
            environment: dict[str, str],
            timeout: float,
        ) -> InstallerCommandResult:
            result = execute(installer, args, project, environment, timeout)
            if len(installer.calls) == 2:
                damage(Path(environment["HOME"]), project)
            return result

        monkeypatch.setattr(LiteralInstaller, "execute", install)
    result, installer = conduct_preserve_skill_backup(tmp_path)
    assert result.status == "failed"
    assert len(installer.calls) == (1 if phase == "preparation" else 2)


def test_first_install_backup_blocks_skill_mutation(tmp_path: Path) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, first_backup=True)
    assert result.status == "failed" and len(installer.calls) == 1
    assert result.steps[1].phase == "idle"
    assert not (tmp_path / "proof/intermediate/operation.json").exists()


def test_empty_reference_tree_does_not_block_backup_preservation(tmp_path: Path) -> None:
    result, installer = conduct_preserve_skill_backup(tmp_path, empty=True)
    assert result.status == "passed" and len(installer.calls) == 2
