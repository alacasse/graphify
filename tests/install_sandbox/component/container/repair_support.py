"""Controlled repair fixtures with physical mutation and persistence fault seams."""

import json
import shutil
from pathlib import Path
from typing import Literal, NotRequired, TypedDict
from unittest.mock import patch

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container import intermediate_execution
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.file_mutation import apply_mutation
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import ArtifactReceipt
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence
from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact


class FixtureVector(TypedDict):
    case: str
    fault: NotRequired[Literal["wrong-mutation", "persist-before-mutation"]]


class FixtureOutcome(TypedDict):
    run_status: str
    replay_status: str
    calls: int
    proof: str


def replay(proof: Path) -> str:
    try:
        return read_evidence(proof).status
    except MalformedEvidence:
        return "invalid"


def run_fixture(root: Path, vector: FixtureVector) -> FixtureOutcome:
    subject, spec, context = arrange(root)
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in cases.cases if case.name == vector["case"])
    case_file = root / "case.json"
    case.write(case_file)
    installer = LiteralInstaller()
    fault = vector.get("fault")
    original_apply = apply_mutation
    original_retain = TestResultWriter.retain

    def apply(
        operation: BoundMarkdownMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        original_apply(operation, environment, case_bytes, first_after, sources)
        if fault == "wrong-mutation":
            (environment.project / "GUIDE.md").write_text("Wrong mutation.\n")

    def retain(
        writer: TestResultWriter, artifact: JsonArtifact | SnapshotArtifact
    ) -> ArtifactReceipt:
        if (
            fault == "persist-before-mutation"
            and artifact.reference == "intermediate/operation.json"
        ):
            raise OSError("Injected persistence failure")
        return original_retain(writer, artifact)

    with (
        patch.object(intermediate_execution, "apply_mutation", apply),
        patch.object(TestResultWriter, "retain", retain),
    ):
        result = InstallTestRunner(InstallerDriver(installer.execute)).run_case(
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
