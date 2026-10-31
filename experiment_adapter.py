"""Test-only controlled installer and physical fault seams; verdicts belong to public APIs."""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from typing import TypedDict, Required
from tests.install_sandbox.component.host.native_support import arrange, LiteralInstaller
from tools.install_sandbox.contracts.effect_case import build_effect_cases, SubjectContext
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence, MalformedEvidence
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.environment import ObservedEnvironment
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation


class FixtureVector(TypedDict, total=False):
    case: Required[str]
    repair: str
    first_wrong: bool
    exit_stage: str
    changed_effect: str | None
    neighbor: str
    fault: str


class FixtureOutcome(TypedDict):
    run_status: str
    replay_status: str
    calls: int
    proof: str


def replay(proof: Path) -> str:
    try:
        return read_evidence(Path(proof)).status
    except MalformedEvidence:
        return "invalid"


def run_fixture(root: Path, vector: FixtureVector) -> FixtureOutcome:
    subject, spec, context = arrange(root)
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(c for c in cases.cases if c.name == vector["case"])
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller()
    neighbor = None

    def execute(args, project, environment, timeout):
        nonlocal neighbor
        result = installer.execute(args, project, environment, timeout)
        target = project / "GUIDE.md"
        # Existing fixture personal skill file is protected and already declared.
        if neighbor is None:
            neighbor = Path(environment["HOME"]) / ".synthetic/skills/package/personal.txt"
        if not neighbor.exists() and len(installer.calls) == 1:
            # Locate fixture personal data instead of introducing undeclared content.
            candidates = list(project.rglob("*")) + list(
                (Path(environment["HOME"]) / ".synthetic").rglob("*")
            )
            neighbor = next(
                (p for p in candidates if p.is_file() and "personal" in p.name), neighbor
            )
        if len(installer.calls) == 1 and vector.get("first_wrong"):
            target.write_text(
                "## Personal before\nKeep before.\n\n## graphify\nWrong.\n## Personal after\nKeep after.\n\n"
            )
        if len(installer.calls) == 2:
            if vector.get("repair") is not None:
                target.write_text(vector["repair"])
            effect = vector.get("changed_effect")
            paths = {
                "skill": Path(environment["HOME"]) / ".synthetic/skills/package/SKILL.md",
                "backup": project / ".synthetic/config.json.graphify-bak",
                "hooks": project / ".synthetic/config.json",
            }
            if effect:
                paths[effect].write_text("Changed effect.\n")
            mode = vector.get("neighbor")
            if mode == "added":
                (project / "unexpected-personal").write_text("Personal neighbor.\n")
            elif mode == "modified":
                neighbor.write_text("Changed neighbor.\n")
            elif mode == "deleted":
                neighbor.unlink()
            elif mode == "type-changed":
                neighbor.unlink()
                neighbor.mkdir()
            elif mode == "target-directory":
                target.unlink()
                target.mkdir()
            elif mode == "target-symlink":
                target.unlink()
                link = root / "symlink-target"
                link.write_text("Personal neighbor.\n")
                target.symlink_to(link)
        stage = "first" if len(installer.calls) == 1 else "repair"
        return replace(result, exit_code=7) if vector.get("exit_stage") == stage else result

    fault = vector.get("fault")
    original_apply = BoundMarkdownMutation.apply
    original_observe = EffectEnvironment.observe_intermediate
    original_write = TestResultWriter.write_metadata
    original_snapshot = TestResultWriter.write_intermediate_snapshot
    original_regular_observe = EffectEnvironment.observe
    original_file = ObservedEnvironment._file
    capture_stage = None

    def apply(self, environment, *args):
        original_apply(self, environment, *args)
        if fault == "wrong-mutation":
            (environment.project / "GUIDE.md").write_text("Wrong mutation.\n")
        if fault == "preparation-neighbor-change":
            (environment.project / "unexpected-neighbor").write_text("Changed neighbor.\n")

    def observe(self, writer, phase):
        nonlocal capture_stage
        capture_stage = "partial-" + phase + "-mutation"
        if fault == "capture-" + phase + "-mutation":
            raise OSError("Injected capture failure")
        return original_observe(self, writer, phase)

    def regular_observe(self, writer, phase, *, step_index=0):
        nonlocal capture_stage
        capture_stage = "partial-" + phase + "-repair" if step_index == 1 else None
        return original_regular_observe(self, writer, phase, step_index=step_index)

    def capture_file(self, snapshot, entry, path):
        if (
            fault == capture_stage
            and fault is not None
            and fault.startswith("partial-")
            and entry["root"] == "project"
            and path.parent == self.project
            and path.name.startswith("personal-effect-")
        ):
            entry["content_file"] = None
            snapshot.obstacles.append(
                {
                    "operation": "read_file",
                    "root": entry["root"],
                    "path": entry["path"],
                    "reason": "Injected unavailable personal bytes",
                }
            )
            return
        return original_file(self, snapshot, entry, path)

    def write(self, name, data):
        wanted = {
            "persist-before-mutation": "intermediate/operation.json",
            "persist-after-mutation": "intermediate/after.json",
        }.get(fault)
        if name == wanted:
            raise OSError("Injected persistence failure")
        return original_write(self, name, data)

    def snapshot(self, observation, phase):
        if fault == "persist-after-mutation" and phase == "after":
            raise OSError("Injected persistence failure")
        return original_snapshot(self, observation, phase)

    with (
        patch.object(EffectEnvironment, "observe", regular_observe),
        patch.object(ObservedEnvironment, "_file", capture_file),
        patch.object(TestResultWriter, "write_intermediate_snapshot", snapshot),
        patch.object(BoundMarkdownMutation, "apply", apply),
        patch.object(EffectEnvironment, "observe_intermediate", observe),
        patch.object(TestResultWriter, "write_metadata", write),
    ):
        result = InstallTestRunner(InstallerDriver(execute)).run_case(
            reference_sources=subject,
            prepared_executable=root / "executable",
            case_file=case_file,
            work_directory=root / "work",
            output_directory=root / "proof",
        )
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    case_file.unlink()
    spec.unlink()
    context.unlink()
    proof = root / "proof"
    return {
        "run_status": result.status,
        "replay_status": replay(proof),
        "calls": len(installer.calls),
        "proof": str(proof),
    }


def tamper(proof, kind):
    proof = Path(proof)
    if kind in {"environment-first", "environment-repair"}:
        index = 0 if kind == "environment-first" else 1
        (proof / f"steps/{index}/environment.json").unlink()
        return
    if kind == "command-shape":
        p = proof / "result.json"
        data = json.loads(p.read_text())
        for step in data["steps"]:
            step["command"]["args"][0] = None
            step["command"]["reason"] = {"malformed": True}
        p.write_text(json.dumps(data))
        return
    if kind == "event-shape":
        p = proof / "result.json"
        data = json.loads(p.read_text())
        data["intermediate_preparation"] = None
        p.write_text(json.dumps(data))
        return
    if kind == "missing-required":
        (proof / "steps/0/after.json").unlink()
        return
    if kind == "forbidden-later":
        (proof / "intermediate").mkdir(exist_ok=True)
        (proof / "intermediate/after.json").write_text("{}")
        return
    if kind == "case-identity":
        p = proof / "case.json"
        data = json.loads(p.read_text())
        data["name"] = "forged"
        p.write_text(json.dumps(data))
        return
    if kind == "verdict":
        p = proof / "intermediate/verification.json"
        data = json.loads(p.read_text())
        data["complete"] = False
        p.write_text(json.dumps(data))
        return
    if kind == "observation":
        p = proof / "steps/1/after.json"
        data = json.loads(p.read_text())
        data["entries"] = []
        p.write_text(json.dumps(data))
        return
    if kind == "source":
        for p in proof.rglob("*"):
            if p.is_file() and p.read_bytes() == b"## graphify\nConsult the synthetic map.\n":
                p.write_bytes(b"Wrong source.\n")
                return
        raise ValueError("Retained source blob not found")
    raise ValueError(kind)
