"""Literal Agents subject exercised through the normal runner and retained replay."""

import hashlib
import shutil
from pathlib import Path

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

SPEC = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/agents.yaml"


def conduct_uninstall(
    root: Path, *, fault: str | None = None
) -> tuple[InstallTestResult, list[list[str]]]:
    subject = root / "subject"
    write(subject / "skill-agents.md", "# Controlled Agents skill\n")
    write(subject / "skills/agents/references/nested/reference.md", "Agents reference.\n")
    write(subject / "METADATA", "Metadata-Version: 2.4\nName: controlled\nVersion: 8.7.6\n")
    context = SubjectContext(
        "controlled-agents",
        ("install", "--platform", "agents", "--project"),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        uninstall_invocation=("uninstall", "--platform", "agents", "--project"),
        uninstall_user_skill_path=".agents/skills/graphify",
    )
    cases = build_effect_cases(EffectSpecReader().read(SPEC), context)
    case = next(case for case in cases.cases if case.name == "uninstall")
    case_file = root / "case.json"
    case.write(case_file)
    calls: list[list[str]] = []

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert timeout == 60
        calls.append(args)
        skill = project / ".agents/skills/graphify"
        if len(calls) == 1:
            assert args[1:] == ["install", "--platform", "agents", "--project"]
            if fault == "install-exit":
                return InstallerCommandResult(args, str(project), "completed", 7, None)
            if fault != "install-false-success":
                write(skill / "SKILL.md", "# Controlled Agents skill\n")
                write(skill / "references/nested/reference.md", "Agents reference.\n")
                write(skill / ".graphify_version", "8.7.6")
                digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
                write(Path(environment["HOME"]) / f".cache/graphify/skill-locks/{digest}.lock", "")
        else:
            assert args[1:] == ["uninstall", "--platform", "agents", "--project"]
            if fault != "uninstall-false-success":
                (skill / "SKILL.md").unlink()
                (skill / ".graphify_version").unlink()
                shutil.rmtree(skill / "references")
            damaged = {
                "personal": project / ".agents/skills/personal-effect-0.txt",
                "skill-personal": skill / "personal.txt",
                "backup": skill / "SKILL.md.bak",
                "graph-output": project / "graphify-out/personal.txt",
                "user-skill": Path(environment["HOME"]) / ".agents/skills/graphify/SKILL.md",
            }.get(fault or "")
            if damaged is not None:
                damaged.write_text("Damaged\n")
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
