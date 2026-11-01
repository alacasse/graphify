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


def _fail_publication(monkeypatch: pytest.MonkeyPatch, window: str, target: str) -> list[str]:
    original_create = cast(Callable[..., Any], evidence_writer.tempfile.NamedTemporaryFile)
    original_dump = evidence_writer.json.dump
    original_replace = Path.replace
    original_write = cast(
        Callable[..., None], vars(evidence_writer.TestResultWriter)["_write_json"]
    )
    attempts: list[str] = []
    armed = False
    basename = Path(target).name

    def write(writer: Any, relative: str, value: Any) -> None:
        nonlocal armed
        selected = relative == target and (
            relative != "result.json"
            or value.get("intermediate_preparation", {}).get("stage") == "mutation_recorded"
        )
        armed = selected
        if selected:
            attempts.append(relative)
        try:
            original_write(writer, relative, value)
        finally:
            armed = False

    class ClosingStream:
        def __init__(self, stream: Any) -> None:
            self.stream = stream

        def __enter__(self) -> Any:
            return self.stream

        def __exit__(self, *args: Any) -> None:
            if window == "close-before":
                # Close only after the injected failure, as exception unwinding would.
                try:
                    raise OSError("Controlled failure before close")
                finally:
                    self.stream.close()
            self.stream.close()
            if window == "close-after":
                raise OSError("Controlled failure after close")

    def create(*args: Any, **kwargs: Any) -> Any:
        selected = armed and kwargs.get("prefix") == f".{basename}."
        if selected and window == "create-before":
            raise OSError("Controlled tempfile creation failure")
        stream = original_create(*args, **kwargs)
        if selected and window == "create-after":
            stream.close()
            raise OSError("Controlled interruption after tempfile creation")
        return ClosingStream(stream) if selected else stream

    def dump(value: Any, stream: Any, *args: Any, **kwargs: Any) -> None:
        if armed and window == "write-before":
            raise OSError("Controlled failure before write")
        if armed and window == "write-partial":
            stream.write('{"partial":')
            raise OSError("Controlled partial write")
        original_dump(value, stream, *args, **kwargs)
        if armed and window == "write-after":
            raise OSError("Controlled failure after write")

    def replace(source: Path, destination: Any) -> Path:
        selected = armed and source.name.startswith(f".{basename}.")
        if selected and window == "rename-before":
            raise OSError("Controlled atomic replace failure")
        result = original_replace(source, destination)
        if selected and window == "rename-after":
            raise OSError("Controlled interruption after atomic replace")
        return result

    monkeypatch.setattr(evidence_writer.TestResultWriter, "_write_json", write)
    monkeypatch.setattr(evidence_writer.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(evidence_writer.json, "dump", dump)
    monkeypatch.setattr(Path, "replace", replace)
    return attempts


def _run_interrupted(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    window: str,
    target: str = "intermediate/operation.json",
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
    attempts = _fail_publication(monkeypatch, window, target)
    outcome = InstallTestRunner(InstallerDriver(installer.execute)).run_case(
        reference_sources=subject,
        prepared_executable=root / "controlled-executable",
        case_file=root / "case.json",
        work_directory=root / "work",
        output_directory=root / "proof",
    )
    assert outcome.status == "incomplete"
    assert len(installer.calls) == 1
    assert len(mutations) == int(target == "result.json")
    expected_stage, generation = {
        "intermediate/operation.json": ("started", 1),
        "intermediate/before.json": ("repair_plan_retained", 4),
        "result.json": (
            ("mutation_recorded", 6) if window == "rename-after" else ("before_retained", 5)
        ),
    }[target]
    assert attempts == [target]
    published = json.loads((root / "proof/result.json").read_text())
    assert published["intermediate_preparation"] == {
        "stage": expected_stage,
        "generation": generation,
        "reason": None,
    }
    # A failed acknowledgement leaves memory behind the durable checkpoint.
    expected_memory = (
        {"stage": "before_retained", "generation": 5, "reason": None}
        if target == "result.json"
        else published["intermediate_preparation"]
    )
    assert outcome.intermediate_preparation == expected_memory
    shutil.rmtree(subject)
    shutil.rmtree(root / "work")
    (root / "case.json").unlink()
    spec.unlink()
    context.unlink()
    return root / "proof"


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize(
    "window",
    [
        "create-before",
        "create-after",
        "write-before",
        "write-partial",
        "write-after",
        "close-before",
        "close-after",
        "rename-before",
        "rename-after",
    ],
)
@pytest.mark.parametrize(
    "target", ["intermediate/operation.json", "intermediate/before.json", "result.json"]
)
def test_real_atomic_operation_failure_replays_incomplete_without_dependent_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    window: str,
    target: str,
) -> None:
    proof = _run_interrupted(tmp_path, monkeypatch, scenario, window, target)
    assert read_evidence(proof).status == "incomplete"


@pytest.mark.parametrize("future", ["before", "after", "unrelated"])
def test_empty_future_directory_does_not_become_admissible_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, future: str
) -> None:
    proof = _run_interrupted(tmp_path, monkeypatch, "missing-section", "create-before")
    (proof / "intermediate" / future).mkdir()
    with pytest.raises(MalformedEvidence):
        read_evidence(proof)
