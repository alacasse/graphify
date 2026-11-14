"""Three-command scope sequences retain independently replayable evidence."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import (
    LiteralInstaller,
    arrange,
    read_project_effects,
)
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.host.result_reader import read_evidence
from tools.install_sandbox.host.evidence_reader import retained_snapshot
from tools.install_sandbox.rules.step_lifecycle import status


class ScopeInstaller:
    """Literal fixture with explicit scope commands and deliberate product faults."""

    def __init__(self, fault: str | None = None) -> None:
        self.fault = fault
        self.calls: list[list[str]] = []
        self.project = LiteralInstaller(markdown=False, hooks=False, skill_root="project")
        self.user = LiteralInstaller(markdown=False, hooks=False, skill_root="home")

    def execute(
        self,
        args: list[str],
        project: Path,
        environment: dict[str, str],
        timeout: float,
    ) -> InstallerCommandResult:
        self.calls.append(args)
        home = Path(environment["HOME"])
        skill = project / ".synthetic/skills/package"
        if self.fault == "prerequisite" and len(self.calls) == 1:
            return InstallerCommandResult(args, str(project), "completed", 1, None)
        if "uninstall" in args:
            (skill / "SKILL.md").unlink()
            (skill / ".graphify_version").unlink()
            references = skill / "references"
            if self.fault == "empty-references":
                shutil.rmtree(references)
                references.mkdir()
            else:
                shutil.rmtree(references)
            if self.fault == "backup":
                (skill / "SKILL.md.bak").unlink()
            if self.fault == "home":
                (home / ".synthetic/skills/package/SKILL.md").write_text("damaged user skill")
            return InstallerCommandResult(args, str(project), "completed", 0, None)
        installer = self.user if "user" in args else self.project
        result = installer.execute(args, project, environment, timeout)
        if self.fault == "project" and "user" in args:
            (skill / "SKILL.md").write_text("damaged project skill")
        return result


def run_scope(
    root: Path,
    operation: str,
    fault: str | None = None,
) -> tuple[EffectInstallCase, Path, ScopeInstaller]:
    subject, spec_file, context_file = arrange(
        root,
        markdown=False,
        hooks=False,
        skill_root="project",
    )
    project = read_project_effects(spec_file)
    effect = project.effects[0]
    assert isinstance(effect, SkillEffect)
    user = EffectSpec(
        (replace(effect, destination=Destination("home", effect.destination.path)),), "user"
    )
    context = replace(
        SubjectContext.from_data(json.loads(context_file.read_text())),
        invocations={
            "synthetic:project": ("install", "project"),
            "synthetic:user": ("install", "user"),
        },
        prerequisites={"synthetic:user": "synthetic:project"},
        uninstall_invocations={"synthetic:project": ("uninstall", "project")},
    )
    target, prerequisite, participant = (
        (project, user, "synthetic:user")
        if operation == "uninstall"
        else (user, project, "synthetic:project")
    )
    cases = build_effect_cases(
        target,
        context,
        "synthetic",
        prerequisite_effects=prerequisite,
        prerequisite_participant=participant,
    ).cases
    case = next(case for case in cases if case.key.operation == operation)
    case.write(root / "case.json")
    executable = root / "prepared-executable"
    executable.write_text("Literal fixture identity.\n")
    installer = ScopeInstaller(fault)
    output = root / "result"
    InstallTestRunner(InstallerDriver(installer.execute)).run_case(
        reference_sources=subject,
        prepared_executable=executable,
        case_file=root / "case.json",
        work_directory=root / "work",
        output_directory=output,
    )
    return case, output, installer


@pytest.mark.parametrize("operation", ["reinstall", "missing-reference", "uninstall"])
def test_three_scope_commands_pass_and_replay(tmp_path: Path, operation: str) -> None:
    case, output, installer = run_scope(tmp_path, operation)
    replay = read_evidence(output)
    assert replay.status == "passed"
    assert len(installer.calls) == len(replay.steps) == 3
    assert [step.intent for step in replay.steps] == [
        {"index": index, **step.to_data()} for index, step in enumerate(case.steps)
    ]
    if operation == "uninstall":
        installed = retained_snapshot(output, "steps/1/after.json")
        removed = retained_snapshot(output, "steps/2/after.json")
        before = {(entry["root"], entry["path"]) for entry in installed.entries}
        after = {(entry["root"], entry["path"]) for entry in removed.entries}
        managed = ("project", ".synthetic/skills/package/SKILL.md")
        backup = ("project", ".synthetic/skills/package/SKILL.md.bak")
        personal = ("project", ".synthetic/skills/package/personal.txt")
        assert managed in before and managed not in after
        assert backup in before & after and personal in before & after


@pytest.mark.parametrize(
    ("operation", "fault", "commands", "states"),
    [
        ("reinstall", "prerequisite", 1, ["failed", "not_run", "not_run"]),
        ("reinstall", "project", 2, ["passed", "failed", "not_run"]),
        ("uninstall", "empty-references", 3, ["passed", "passed", "failed"]),
        ("uninstall", "backup", 3, ["passed", "passed", "failed"]),
        ("uninstall", "home", 3, ["passed", "passed", "failed"]),
    ],
)
def test_scope_faults_fail_and_block_dependents(
    tmp_path: Path,
    operation: str,
    fault: str,
    commands: int,
    states: list[str],
) -> None:
    _, output, installer = run_scope(tmp_path, operation, fault)
    result = read_evidence(output)
    assert result.status == "failed"
    assert [status(step) for step in result.steps] == states
    assert len(installer.calls) == commands


@pytest.mark.parametrize("fault", ["missing-observation", "intent"])
def test_scope_replay_rejects_missing_or_rebound_receipts(tmp_path: Path, fault: str) -> None:
    _, output, _ = run_scope(tmp_path, "uninstall")
    assert read_evidence(output).status == "passed"
    if fault == "missing-observation":
        (output / "steps/1/after.json").unlink()
    else:
        path = output / "result.json"
        payload = json.loads(path.read_text())
        payload["steps"][2]["intent"]["index"] = 1
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(output)


def test_uninstall_partial_receipt_and_staging_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = ScopeInstaller.execute

    def interrupted(
        self: ScopeInstaller,
        args: list[str],
        project: Path,
        environment: dict[str, str],
        timeout: float,
    ) -> InstallerCommandResult:
        if "uninstall" in args:
            raise OSError("Controlled interruption before removal")
        return execute(self, args, project, environment, timeout)

    monkeypatch.setattr(ScopeInstaller, "execute", interrupted)
    _, output, _ = run_scope(tmp_path, "uninstall")
    result = read_evidence(output)
    assert result.status == "incomplete"
    assert result.steps[2].stop is not None
    assert result.steps[2].stop.phase == "command"
    assert result.steps[2].retained.expectations == "expectations/uninstall.json"
    assert not (output / "expectations/reinstall.json").exists()
    (output / "expectations/.uninstall.json.controlled.tmp").write_text("partial write")
    assert read_evidence(output).status == "incomplete"
    (output / "expectations/uninstall.json").unlink()
    with pytest.raises(ValueError):
        read_evidence(output)


@pytest.mark.parametrize(
    ("operation", "foreign"),
    [
        ("reinstall", "uninstall"),
        ("reinstall", "intermediate"),
        ("uninstall", "reinstall"),
        ("uninstall", "intermediate"),
    ],
)
@pytest.mark.parametrize("staging", [False, True])
def test_scope_replay_rejects_expectations_from_another_sequence(
    tmp_path: Path,
    operation: str,
    foreign: str,
    staging: bool,
) -> None:
    _, output, _ = run_scope(tmp_path, operation)
    assert read_evidence(output).status == "passed"
    name = f".{foreign}.json.foreign.tmp" if staging else f"{foreign}.json"
    (output / "expectations" / name).write_text("{}")
    with pytest.raises(ValueError, match="Unknown|contradicts retained later evidence"):
        read_evidence(output)
