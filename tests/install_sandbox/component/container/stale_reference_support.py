"""Run one stale reference removal with a literal installer and replay its retained proof."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from tests.install_sandbox.component.host.native_support import (
    LiteralInstaller,
    arrange,
    read_project_effects,
)
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.result_reader import read_evidence


def conduct_stale_reference(
    root: Path,
    *,
    skill_root: Literal["home", "project"] = "home",
    repair_fault: str | None = None,
) -> tuple[InstallTestResult, LiteralInstaller]:
    subject, spec, context = arrange(root, skill_root=skill_root)
    cases = build_effect_cases(
        read_project_effects(spec),
        SubjectContext.from_data(json.loads(context.read_text())),
    )
    case = next(case for case in cases.cases if case.name == "stale-reference")
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller(skill_root=skill_root)

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        home = Path(environment["HOME"])
        skill = (home if skill_root == "home" else project) / ".synthetic/skills/package"
        installer.rebuild_references = repair_fault != "overlay"
        result = installer.execute(args, project, environment, timeout)
        if len(installer.calls) == 2:
            if repair_fault == "reference":
                reference = skill / "references/nested/reference.md"
                content = reference.read_bytes()
                reference.write_bytes(bytes([content[0] ^ 1]) + content[1:])
            elif repair_fault == "skill":
                (skill / "SKILL.md").write_bytes(b"Unexpected damage\n")
            elif repair_fault == "personal":
                (project / "personal-effect-1.txt").unlink()
        return result

    result = run_retained_reference_case(root, subject, spec, context, execute)
    return result, installer


def run_retained_reference_case(
    root: Path,
    subject: Path,
    spec: Path,
    context: Path,
    execute: Callable[[list[str], Path, dict[str, str], float], InstallerCommandResult],
) -> InstallTestResult:
    """Run the prepared case and reconstruct its result after removing live inputs."""
    case_file = root / "case.json"
    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=case_file,
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    shutil.rmtree(subject)
    shutil.rmtree(root / "work", ignore_errors=True)
    for path in (case_file, spec, context):
        path.unlink()
    assert read_evidence(root / "proof") == result
    return result
