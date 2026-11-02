"""Decode current results and replay retained evidence without external inputs."""

import json
from pathlib import Path

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import (
    InstallTestResult,
    IntermediateEvidence,
    StepState,
)
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.effect_result_reader import check_effect_result
from tools.install_sandbox.host.evidence_reader import (
    json_list as _list,
)
from tools.install_sandbox.host.evidence_reader import (
    json_object as _json_object,
)
from tools.install_sandbox.host.evidence_reader import (
    optional_text as _optional_text,
)
from tools.install_sandbox.host.evidence_reader import (
    read_json_evidence as _read_json_evidence,
)
from tools.install_sandbox.host.evidence_reader import (
    safe_evidence_path,
)
from tools.install_sandbox.rules.initial_preparation import status as initial_status
from tools.install_sandbox.rules.step_lifecycle import status, validate


def _evidence(value: object, output: Path) -> str | None:
    result = _optional_text(value)
    if result is not None:
        safe_evidence_path(output, result)
    return result


def _step(value: object, output: Path) -> StepState:
    step = StepState.from_data(value)
    validate(step)
    for reference in (step.observations or {}).values():
        _evidence(reference, output)
    if step.command is not None:
        _evidence(step.command["stdout_file"], output)
        _evidence(step.command["stderr_file"], output)
    return step


def _intermediate(value: object, output: Path) -> IntermediateEvidence | None:
    if value is None:
        return None
    data = fields(value, "stage generation reason")
    generation = data["generation"]
    if type(generation) is not int or generation < 0:
        raise ValueError("Expected nonnegative checkpoint generation")
    return {
        "stage": text(data["stage"]),
        "generation": generation,
        "reason": _optional_text(data["reason"]),
    }


def _check_consistency(result: InstallTestResult, repair_diagnostic: str | None) -> None:
    if result.preparation.checkpoint != "ready":
        expected = initial_status(result.preparation)
        if any(step.phase != "idle" for step in result.steps) or result.status != expected:
            raise ValueError("Initial preparation contradicts case progression")
        return
    aggregate = "passed"
    for index, step in enumerate(result.steps):
        if index == 1 and repair_diagnostic is not None and aggregate == "passed":
            aggregate = repair_diagnostic
        if aggregate != "passed":
            if step.phase != "idle":
                raise ValueError("Dependent step requires published passed predecessor")
            continue
        aggregate = "incomplete" if step.phase == "idle" else status(step)
    if result.status != aggregate:
        raise ValueError("Case status contradicts command or verification facts")


def _read_result(output_directory: Path, case: EffectInstallCase) -> InstallTestResult:
    """Read a complete result; retain I/O failures and reject incompatible documents."""
    payload = safe_evidence_path(output_directory, "result.json").read_text(encoding="utf-8")
    data = fields(
        json.loads(payload, object_pairs_hook=_json_object),
        "case preparation steps status evidence intermediate_preparation",
    )
    identity = fields(data["case"], "name target scope")
    expected = {"name": case.name, "target": case.target, "scope": case.scope}
    if identity != expected:
        raise ValueError("Result case identity does not match the requested case")
    status = text(data["status"])
    if status not in ("passed", "failed", "not_run", "incomplete"):
        raise ValueError("Invalid case result status")
    steps = [_step(item, output_directory) for item in _list(data["steps"])]
    if [step.operation for step in steps] != case.operations:
        raise ValueError("Result steps do not match the requested operations")
    result = InstallTestResult(
        expected,
        InitialPreparationState.from_data(data["preparation"]),
        steps,
        status,
        {
            key: _evidence(value, output_directory)
            for key, value in fields(data["evidence"], "journal").items()
        },
    )
    result.intermediate_preparation = _intermediate(
        data["intermediate_preparation"], output_directory
    )
    if (result.intermediate_preparation is None) != (case.intermediate_preparation is None):
        raise ValueError("Intermediate evidence contradicts case definition")
    repair_diagnostic = check_effect_result(result, case, output_directory)
    _check_consistency(result, repair_diagnostic)
    return result


def _read_evidence(output_directory: Path) -> InstallTestResult:
    """Rebuild and validate verdicts entirely from retained native evidence."""
    if _read_json_evidence(output_directory, "evidence-format.json") != {
        "format": "explicit-expectations-v7"
    }:
        raise ValueError("Unsupported evidence format; use its identified historical reader")
    case = EffectInstallCase.from_json(
        safe_evidence_path(output_directory, "case.json").read_text(encoding="utf-8")
    )
    return _read_result(output_directory, case)


class MalformedEvidence(ValueError):
    """The retained archive cannot support its claimed durable facts."""


def read_evidence(output_directory: Path) -> InstallTestResult:
    try:
        return _read_evidence(output_directory)
    except (ValueError, OSError, UnicodeError) as error:
        raise MalformedEvidence(str(error)) from error
