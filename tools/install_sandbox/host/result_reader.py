"""Decode current results and replay retained evidence without external inputs."""

import json
from pathlib import Path

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import (
    InstallTestResult,
    IntermediateEvidence,
    RepairCheckpoint,
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
from tools.install_sandbox.rules.case_progression import CaseFacts, CaseShape, evaluate
from tools.install_sandbox.rules.step_lifecycle import validate


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


def _intermediate(value: object) -> IntermediateEvidence | None:
    return None if value is None else RepairCheckpoint.from_data(value).to_data()


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
    result.intermediate_preparation = _intermediate(data["intermediate_preparation"])
    if (result.intermediate_preparation is None) != (case.intermediate_preparation is None):
        raise ValueError("Intermediate evidence contradicts case definition")
    repair = check_effect_result(result, case, output_directory)
    decision = evaluate(
        CaseShape.from_case(case),
        CaseFacts(result.preparation, (steps[0], steps[1]), repair),
    )
    if result.status != decision.status:
        raise ValueError("Case status contradicts published local progression")
    return result


def _read_evidence(output_directory: Path) -> InstallTestResult:
    """Rebuild and validate verdicts entirely from retained native evidence."""
    if _read_json_evidence(output_directory, "evidence-format.json") != {
        "format": "explicit-expectations-v8"
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
