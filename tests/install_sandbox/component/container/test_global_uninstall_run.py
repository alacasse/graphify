"""Global removal and purge replay from an identical two-HOME installation."""

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

SPEC = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/global-uninstall.yaml"
COMMANDS = (
    ("install", "--platform", "agents"),
    ("install", "--platform", "copilot"),
    ("uninstall",),
)


def conduct_global(
    root: Path, *, purge: bool, fault: str | None = None
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
        uninstall_invocation=COMMANDS[2],
        purge_invocation=("uninstall", "--purge"),
        group_install_invocations=COMMANDS[:2],
    )
    case = build_effect_cases(EffectSpecReader().read(SPEC), context).cases[int(purge)]
    case_file = root / "case.json"
    case.write(case_file)
    calls: list[list[str]] = []

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        index = len(calls)
        calls.append(args)
        expected = (
            COMMANDS[index]
            if index < 2
            else (("uninstall", "--purge") if purge else ("uninstall",))
        )
        assert tuple(args[1:]) == expected
        assert timeout == 60
        home = Path(environment["HOME"])
        if index < 2:
            if fault == "early-exit" and index == 0:
                return InstallerCommandResult(args, str(project), "completed", 7, None)
            if not (fault == "install-false-success" and index == 1):
                platform = "agents" if index == 0 else "copilot"
                skill = home / f".{platform}/skills/graphify"
                write(skill / "SKILL.md", f"# Controlled {platform} skill\n")
                write(skill / "references/nested/reference.md", f"{platform} reference.\n")
                write(skill / ".graphify_version", "8.7.6")
                digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
                write(home / f".cache/graphify/skill-locks/{digest}.lock", "")
        else:
            if fault != "skip-removal":
                for platform in ("agents", "copilot"):
                    skill = home / f".{platform}/skills/graphify"
                    (skill / "SKILL.md").unlink()
                    (skill / ".graphify_version").unlink()
                    shutil.rmtree(skill / "references")
            if (purge and fault != "no-purge") or fault == "wrong-purge":
                shutil.rmtree(project / "graphify-out")
            if fault == "project-neighbor-loss":
                (project / ".agents/skills/graphify/personal.txt").unlink()
            if fault == "adjacent-loss":
                (project / "personal-next-to-output.txt").unlink()
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


@pytest.mark.parametrize("purge", [False, True])
def test_global_removal_and_purge_replay_after_cleanup(tmp_path: Path, purge: bool) -> None:
    result, calls = conduct_global(tmp_path, purge=purge)
    assert result.status == "passed" and len(calls) == 3
    final = tmp_path / "proof/steps/2/after"
    assert (final / "project/graphify-out").exists() is not purge
    assert (final / "project/personal-next-to-output.txt").is_file()
    for platform in ("agents", "copilot"):
        skill = final / f"home/.{platform}/skills/graphify"
        assert not (skill / "SKILL.md").exists()
        assert not (skill / "references").exists()
        assert not (skill / ".graphify_version").exists()
        assert (skill / "personal.txt").read_bytes() == b"Personal skill content to preserve.\n"


def snapshot_files(root: Path) -> dict[str, bytes]:
    """Exclude path-bound lock names while comparing the observed installation bytes."""
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "skill-locks" not in path.parts
    }
    locks = sorted(
        path.read_bytes() for path in root.rglob("*.lock") if "skill-locks" in path.parts
    )
    files.update({f"normalized-skill-lock-{index}": content for index, content in enumerate(locks)})
    return files


def test_pair_has_equivalent_initial_and_pre_removal_snapshots(tmp_path: Path) -> None:
    for name, purge in (("ordinary", False), ("purge", True)):
        conduct_global(tmp_path / name, purge=purge)
    for relative in ("initial/before", "steps/1/after"):
        ordinary = tmp_path / "ordinary/proof" / relative
        purge = tmp_path / "purge/proof" / relative
        assert snapshot_files(ordinary) == snapshot_files(purge)
        assert snapshot_files(ordinary)


@pytest.mark.parametrize(
    ("purge", "fault", "count"),
    [
        (True, "no-purge", 3),
        (False, "wrong-purge", 3),
        (False, "adjacent-loss", 3),
        (True, "adjacent-loss", 3),
        (True, "project-neighbor-loss", 3),
        (False, "skip-removal", 3),
        (True, "skip-removal", 3),
        (False, "early-exit", 1),
        (True, "early-exit", 1),
        (False, "install-false-success", 2),
        (True, "install-false-success", 2),
    ],
)
def test_global_false_success_and_early_failure_replay(
    tmp_path: Path, purge: bool, fault: str, count: int
) -> None:
    result, calls = conduct_global(tmp_path, purge=purge, fault=fault)
    assert result.status == "failed" and len(calls) == count
    assert all(step.phase == "idle" for step in result.steps[count:])
    if count == 3:
        verification = result.steps[2].verification
        assert verification is not None and verification.complete and verification.mismatches


@pytest.mark.parametrize("purge", [False, True])
@pytest.mark.parametrize("forgery", ["command", "verdict"])
def test_global_replay_rejects_forged_command_or_verdict(
    tmp_path: Path, purge: bool, forgery: str
) -> None:
    conduct_global(tmp_path, purge=purge, fault="skip-removal" if forgery == "verdict" else None)
    path = tmp_path / "proof/result.json"
    data = json.loads(path.read_text())
    if forgery == "command":
        data["steps"][2]["facts"]["command"]["args"][1] = "install"
    else:
        data["status"] = "passed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")
