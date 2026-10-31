"""Real atomic-publication failures preserve an honest replayable prefix."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container import evidence_writer, intermediate_execution
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


def _fail_publication(monkeypatch: pytest.MonkeyPatch, window: str) -> None:
    original_create = cast(Callable[..., Any], evidence_writer.tempfile.NamedTemporaryFile)
    original_dump = evidence_writer.json.dump

    def create(*args: Any, **kwargs: Any) -> Any:
        selected = kwargs.get("prefix") == ".operation.json."
        if selected and window == "create-before":
            raise OSError("Controlled tempfile creation failure")
        stream = original_create(*args, **kwargs)
        if selected and window == "create-after":
            stream.close()
            raise OSError("Controlled interruption after tempfile creation")
        return stream

    def dump(value: Any, stream: Any, *args: Any, **kwargs: Any) -> None:
        if Path(str(stream.name)).name.startswith(".operation.json.") and window == "write":
            raise OSError("Controlled temporary-file write failure")
        original_dump(value, stream, *args, **kwargs)

    monkeypatch.setattr(evidence_writer.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(evidence_writer.json, "dump", dump)
    _fail_replace(monkeypatch, window)


def _fail_replace(monkeypatch: pytest.MonkeyPatch, window: str) -> None:
    original_replace = Path.replace

    def replace(source: Path, target: Any) -> Path:
        selected = source.name.startswith(".operation.json.")
        if selected and window == "rename-before":
            raise OSError("Controlled atomic replace failure")
        result = original_replace(source, target)
        if selected and window == "rename-after":
            raise OSError("Controlled interruption after atomic replace")
        return result

    monkeypatch.setattr(Path, "replace", replace)


def _run_interrupted(
    root: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, window: str
) -> Path:
    subject, spec, context = arrange(root)
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    ).cases
    next(case for case in cases if case.name == scenario).write(root / "case.json")
    installer = LiteralInstaller()
    mutations: list[object] = []
    mutate = cast(Callable[..., None], intermediate_execution.apply_markdown_mutation)

    def count_mutation(*args: Any, **kwargs: Any) -> None:
        mutations.append(None)
        mutate(*args, **kwargs)

    monkeypatch.setattr(intermediate_execution, "apply_markdown_mutation", count_mutation)
    _fail_publication(monkeypatch, window)
    outcome = InstallTestRunner(InstallerDriver(installer.execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=root / "case.json",
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    assert outcome.status == "incomplete"
    assert len(installer.calls) == 1
    assert mutations == []
    assert outcome.intermediate_preparation == {"stage": "started", "generation": 1, "reason": None}
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    (root / "case.json").unlink()
    spec.unlink()
    context.unlink()
    return root / "proof"


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize(
    "window", ["create-before", "create-after", "write", "rename-before", "rename-after"]
)
def test_real_atomic_operation_failure_replays_incomplete_without_dependent_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, window: str
) -> None:
    proof = _run_interrupted(tmp_path, monkeypatch, scenario, window)
    assert read_evidence(proof).status == "incomplete"


@pytest.mark.parametrize("future", ["before", "after", "unrelated"])
def test_empty_future_directory_does_not_become_admissible_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, future: str
) -> None:
    proof = _run_interrupted(tmp_path, monkeypatch, "missing-section", "create-before")
    (proof / "intermediate" / future).mkdir()
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)
