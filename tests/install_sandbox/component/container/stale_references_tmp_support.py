"""Run one stale references.tmp removal with a literal installer and replay its retained proof."""

import json
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from tests.install_sandbox.component.container.stale_reference_support import (
    run_retained_reference_case,
)
from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader


def _damage_reinstall(skill: Path, project: Path, repair_fault: str | None) -> None:
    if repair_fault == "empty":
        (skill / "references.tmp/stale.md").unlink()
    elif repair_fault == "empty-directory":
        (project / "personal-empty").rmdir()
    elif repair_fault == "reference":
        reference = skill / "references/nested/reference.md"
        content = reference.read_bytes()
        reference.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    elif repair_fault == "skill":
        (skill / "SKILL.md").write_bytes(b"Unexpected damage\n")
    elif repair_fault == "personal":
        (project / "personal-effect-1.txt").unlink()


def conduct_stale_references_tmp(
    root: Path,
    *,
    skill_root: Literal["home", "project"] = "home",
    repair_fault: str | None = None,
    packaged_stale: bool = False,
) -> tuple[InstallTestResult, LiteralInstaller]:
    subject, spec, context = arrange(root, skill_root=skill_root)
    if packaged_stale:
        (subject / "reference-data/stale.md").write_bytes(b"Packaged stale reference.\n")
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in cases.cases if case.name == "stale-references-tmp")
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller(skill_root=skill_root)
    installer.packaged_stale_reference = packaged_stale

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        home = Path(environment["HOME"])
        skill = (home if skill_root == "home" else project) / ".synthetic/skills/package"
        installer.cleanup_references_tmp = repair_fault not in {"residual", "empty"}
        result = installer.execute(args, project, environment, timeout)
        if len(installer.calls) == 1 and repair_fault == "first-empty":
            (skill / "references.tmp").mkdir()
        if len(installer.calls) == 2:
            _damage_reinstall(skill, project, repair_fault)
        return result

    original_prepare = EffectEnvironment.prepare

    def prepare(environment: EffectEnvironment) -> None:
        original_prepare(environment)
        (environment.project / "personal-empty").mkdir()

    with patch.object(EffectEnvironment, "prepare", prepare):
        result = run_retained_reference_case(root, subject, spec, context, execute)
    return result, installer
