"""Public replay and dependent effects at every durable repair publication."""

import json
import shutil
from collections.abc import Callable
from typing import Any, cast
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container import intermediate_execution as transition
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.host.result_reader import read_evidence


class ProcessStopped(BaseException):
    """Simulated process loss bypasses adapter error handling and finalization."""


# Literal protocol destinations: deliberately independent of the production inventory.
ARTIFACTS = [
    "intermediate/operation.json",
    "expectations/intermediate.json",
    "intermediate/repair-plan.json",
    "intermediate/before.json",
    "intermediate/performed.json",
    "intermediate/after.json",
    "intermediate/verification.json",
    "expectations/reinstall.json",
]
BLOBS = ["intermediate/before/project/GUIDE.md", "intermediate/after/project/GUIDE.md"]
STAGES = [
    "started",
    "operation_retained",
    "preparation_expectations_retained",
    "repair_plan_retained",
    "before_retained",
    "mutation_recorded",
    "after_retained",
    "verification_retained",
    "ready",
]


def run_stopped(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    target: str,
    when: str,
    *,
    runtime_error: bool = False,
) -> tuple[int, int, int]:
    subject, spec, context = arrange(root)
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    ).cases
    next(case for case in cases if case.name == scenario).write(root / "case.json")
    installer = LiteralInstaller()
    writes = 0
    mutations = 0
    stopped_writers: list[Writer] = []
    original_write = cast(Callable[[Writer, str, object], None], getattr(Writer, "_write_json"))
    original_bytes = cast(Callable[..., None], getattr(Writer, "_write_bytes"))
    original_mutate = transition.apply_markdown_mutation

    def mutate(
        operation: BoundMarkdownMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
    ) -> None:
        nonlocal mutations
        mutations += 1
        original_mutate(operation, environment, case_bytes, first_after)

    def publish(writer: Writer, relative: str, value: object) -> None:
        nonlocal writes
        matches = relative == target
        if target in STAGES and relative == "result.json":
            checkpoint = cast(dict[str, Any], value).get("intermediate_preparation")
            matches = (
                isinstance(checkpoint, dict)
                and cast(dict[str, Any], checkpoint).get("stage") == target
            )
        if matches:
            stopped_writers.append(writer)
            writes += 1
            if when == "before":
                if runtime_error:
                    raise OSError("Controlled publication error")
                raise ProcessStopped()
        original_write(writer, relative, value)
        if matches and when == "after":
            if runtime_error:
                raise OSError("Controlled publication error")
            raise ProcessStopped()

    def publish_bytes(writer: Writer, relative: str, value: bytes, *, append: bool = False) -> None:
        nonlocal writes
        if relative == target:
            stopped_writers.append(writer)
            writes += 1
            if when == "before":
                if runtime_error:
                    raise OSError("Controlled blob publication error")
                raise ProcessStopped()
        original_bytes(writer, relative, value, append=append)
        if relative == target and when == "after":
            if runtime_error:
                raise OSError("Controlled blob publication error")
            raise ProcessStopped()

    monkeypatch.setattr(Writer, "_write_bytes", publish_bytes)
    monkeypatch.setattr(transition, "apply_markdown_mutation", mutate)
    monkeypatch.setattr(Writer, "_write_json", publish)
    kwargs = dict(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=root / "case.json",
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    if runtime_error:
        result = InstallTestRunner(InstallerDriver(installer.execute)).run_case(**kwargs)
        assert result.status == "incomplete"
        assert len(stopped_writers) == 1 and stopped_writers[0].halted
    else:
        with pytest.raises(ProcessStopped):
            InstallTestRunner(InstallerDriver(installer.execute)).run_case(**kwargs)
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    (root / "case.json").unlink()
    spec.unlink()
    context.unlink()
    assert read_evidence(root / "proof").status == "incomplete"
    return len(installer.calls), mutations, writes


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("target", ARTIFACTS + STAGES + BLOBS)
def test_process_loss_at_each_publication_blocks_dependent_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, when: str, target: str
) -> None:
    calls, mutations, writes = run_stopped(tmp_path, monkeypatch, scenario, target, when)
    assert calls == 1
    expected_mutations = (
        ARTIFACTS.index(target) >= 4
        if target in ARTIFACTS
        else ("/after/" in target if target in BLOBS else STAGES.index(target) >= 5)
    )
    assert mutations == int(expected_mutations)
    assert writes == 1


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("target", ARTIFACTS + STAGES + BLOBS)
def test_publication_error_stops_without_retry_or_dependent_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, when: str, target: str
) -> None:
    calls, mutations, writes = run_stopped(
        tmp_path, monkeypatch, scenario, target, when, runtime_error=True
    )
    assert calls == 1
    expected_mutations = (
        ARTIFACTS.index(target) >= 4
        if target in ARTIFACTS
        else ("/after/" in target if target in BLOBS else STAGES.index(target) >= 5)
    )
    assert mutations == int(expected_mutations)
    assert writes == 1


def test_snapshot_publication_preserves_logical_input(tmp_path: Path) -> None:
    import copy

    snapshot = FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry,
                {
                    "root": "project",
                    "path": "GUIDE.md",
                    "kind": "file",
                    "content_file": None,
                    "sha256": None,
                },
            )
        ],
        contents={("project", "GUIDE.md"): b"Independent bytes.\n"},
    )
    before = copy.deepcopy(snapshot)
    writer = Writer(tmp_path)
    writer.write_intermediate_snapshot(snapshot, "before")
    assert snapshot == before
    manifest = json.loads((tmp_path / "intermediate/before.json").read_text())
    assert manifest["entries"][0]["content_file"] == "intermediate/before/project/GUIDE.md"
    assert snapshot.entries[0].get("content_file") is None
