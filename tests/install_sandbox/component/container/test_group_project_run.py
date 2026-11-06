"""Grouped removal is verified after three independently observed installations."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import write
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence

SPEC = (
    Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/group-uninstall-project.yaml"
)
COMMANDS = (
    ("install", "--platform", "agents"),
    ("install", "--platform", "agents", "--project"),
    ("install", "--platform", "copilot", "--project"),
    ("uninstall", "--project"),
)


def conduct_group(
    root: Path, fault: str | None = None
) -> tuple[InstallTestResult, list[list[str]]]:
    subject = root / "subject"
    for platform in ("agents", "copilot"):
        write(subject / f"skill-{platform}.md", f"# Controlled {platform} skill\n")
        write(
            subject / f"skills/{platform}/references/nested/reference.md",
            f"{platform} reference.\n",
        )
    write(subject / "METADATA", "Metadata-Version: 2.4\nName: controlled\nVersion: 8.7.6\n")
    context = SubjectContext(
        "controlled-group",
        COMMANDS[0],
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        uninstall_invocation=COMMANDS[3],
        group_install_invocations=COMMANDS[:3],
    )
    case = build_effect_cases(EffectSpecReader().read(SPEC), context).cases[0]
    case_file = root / "case.json"
    case.write(case_file)
    calls: list[list[str]] = []

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        index = len(calls)
        calls.append(args)
        assert tuple(args[1:]) == COMMANDS[index]
        assert timeout == 60
        home = Path(environment["HOME"])
        if index < 3:
            if not (fault == "middle-false-success" and index == 1):
                platform = "copilot" if index == 2 else "agents"
                skill = (home if index == 0 else project) / f".{platform}/skills/graphify"
                write(skill / "SKILL.md", f"# Controlled {platform} skill\n")
                write(skill / "references/nested/reference.md", f"{platform} reference.\n")
                write(skill / ".graphify_version", "8.7.6")
                digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
                write(home / f".cache/graphify/skill-locks/{digest}.lock", "")
        elif fault != "uninstall-noop":
            for platform in ("agents", "copilot"):
                skill = project / f".{platform}/skills/graphify"
                (skill / "SKILL.md").unlink()
                (skill / ".graphify_version").unlink()
                shutil.rmtree(skill / "references")
            damaged = {
                "damage-user": home / ".agents/skills/graphify/SKILL.md",
                "damage-neighbor": project / ".copilot/skills/personal-effect-2.txt",
                "damage-output": project / "graphify-out/personal.txt",
            }.get(fault or "")
            if damaged is not None:
                damaged.write_bytes(b"Damaged\n")
        return InstallerCommandResult(args, str(project), "completed", 0, None)

    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=case_file,
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    shutil.rmtree(subject)
    shutil.rmtree(root / "work", ignore_errors=True)
    case_file.unlink()
    assert read_evidence(root / "proof") == result
    return result, calls


def test_group_removal_passes_and_replays_without_execution_environment(tmp_path: Path) -> None:
    result, calls = conduct_group(tmp_path)
    assert result.status == "passed" and len(calls) == 4
    final = tmp_path / "proof/steps/3/after"
    assert (
        final / "home/.agents/skills/graphify/SKILL.md"
    ).read_bytes() == b"# Controlled agents skill\n"
    for platform in ("agents", "copilot"):
        skill = final / f"project/.{platform}/skills/graphify"
        assert not (skill / "SKILL.md").exists()
        assert not (skill / "references").exists()
        assert not (skill / ".graphify_version").exists()
        assert (skill / "personal.txt").read_bytes() == b"Personal skill content to preserve.\n"


def test_middle_install_false_success_blocks_third_install_and_removal(tmp_path: Path) -> None:
    result, calls = conduct_group(tmp_path, "middle-false-success")
    assert result.status == "failed" and len(calls) == 2
    assert result.steps[1].verification is not None
    assert result.steps[1].verification.mismatches
    assert all(step.phase == "idle" for step in result.steps[2:])


@pytest.mark.parametrize(
    "fault", ["uninstall-noop", "damage-user", "damage-neighbor", "damage-output"]
)
def test_successful_exit_does_not_hide_group_removal_or_preservation_failure(
    tmp_path: Path, fault: str
) -> None:
    result, calls = conduct_group(tmp_path, fault)
    assert result.status == "failed" and len(calls) == 4
    verification = result.steps[3].verification
    assert verification is not None and verification.complete and verification.mismatches
    paths = {(item.root, item.path) for item in verification.mismatches}
    if fault == "uninstall-noop":
        assert {
            ("project", f".{platform}/skills/graphify/SKILL.md")
            for platform in ("agents", "copilot")
        } <= paths
    else:
        expected = {
            "damage-user": ("home", ".agents/skills/graphify/SKILL.md"),
            "damage-neighbor": ("project", ".copilot/skills/personal-effect-2.txt"),
            "damage-output": ("project", "graphify-out/personal.txt"),
        }[fault]
        assert paths == {expected}


@pytest.mark.parametrize("forgery", ["command", "expectations"])
def test_group_replay_rejects_forged_command_or_expectations(tmp_path: Path, forgery: str) -> None:
    conduct_group(tmp_path)
    if forgery == "command":
        path = tmp_path / "proof/result.json"
        data = json.loads(path.read_text())
        data["steps"][3]["facts"]["command"]["args"][1] = "install"
    else:
        path = tmp_path / "proof/expectations/uninstall.json"
        data = json.loads(path.read_text())
        data["expectations"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")
