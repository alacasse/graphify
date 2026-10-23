"""Decode current results and replay retained evidence without external inputs."""

import json
from pathlib import Path
from typing import Literal, cast

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    InstallTestResult,
    IntermediateEvidence,
    PreparationEvidence,
    StepEvidence,
)
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.effect_result_reader import check_effect_result
from tools.install_sandbox.host.evidence_reader import (
    boolean as _boolean,
)
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
from tools.install_sandbox.host.evidence_reader import (
    verification as _verification,
)


def _evidence(value: object, output: Path) -> str | None:
    result = _optional_text(value)
    if result is not None:
        safe_evidence_path(output, result)
    return result


def _command(value: object, output: Path) -> CommandEvidence:
    data = fields(value, "args cwd state exit_code reason stdout_file stderr_file")
    state, exit_code = text(data["state"]), data["exit_code"]
    if state not in ("completed", "not_started", "interrupted"):
        raise ValueError("Invalid installer command state")
    if exit_code is not None and type(exit_code) is not int:
        raise ValueError("Command exit_code must be an integer or null")
    if (state == "completed" and exit_code is None) or (
        state == "not_started" and exit_code is not None
    ):
        raise ValueError("Command exit_code is incompatible with its state")
    args = [text(item) for item in _list(data["args"])]
    if not args:
        raise ValueError("Command args cannot be empty")
    return {
        "args": args,
        "cwd": text(data["cwd"]),
        "state": state,
        "exit_code": exit_code,
        "reason": _optional_text(data["reason"]),
        "stdout_file": _evidence(data["stdout_file"], output),
        "stderr_file": _evidence(data["stderr_file"], output),
    }


def _has_failure(value: object) -> bool:
    return isinstance(value, dict) and "failure" in value


def _step(value: object, output: Path) -> StepEvidence:
    failed = _has_failure(value)
    data = fields(
        value,
        "operation progress skip_reason command verification observations"
        + (" failure" if failed else ""),
    )
    observations = data["observations"]
    references = (
        None
        if observations is None
        else {
            key: _evidence(value, output)
            for key, value in fields(observations, "before after").items()
        }
    )
    step: StepEvidence = {
        "operation": text(data["operation"]),
        "progress": _progress(data["progress"]),
        "skip_reason": _optional_text(data["skip_reason"]),
        "command": None if data["command"] is None else _command(data["command"], output),
        "verification": None
        if data["verification"] is None
        else _verification(data["verification"]),
        "observations": references,
    }
    if failed:
        failure = fields(data["failure"], "stage reason")
        step["failure"] = {"stage": text(failure["stage"]), "reason": text(failure["reason"])}
    return step


def _progress(value: object) -> Literal["not_started", "incomplete", "finished"]:
    progress = text(value)
    if progress not in {"not_started", "incomplete", "finished"}:
        raise ValueError("Invalid execution progress")
    return cast(Literal["not_started", "incomplete", "finished"], progress)


def _intermediate(value: object, output: Path) -> IntermediateEvidence | None:
    if value is None:
        return None
    data = fields(value, "progress operation_ref expectations_ref observations verification reason")
    return {
        "progress": _progress(data["progress"]),
        "operation_ref": _evidence(data["operation_ref"], output),
        "expectations_ref": _evidence(data["expectations_ref"], output),
        "observations": {
            key: _evidence(value, output)
            for key, value in fields(data["observations"], "before after").items()
        },
        "verification": None
        if data["verification"] is None
        else _verification(data["verification"]),
        "reason": _optional_text(data["reason"]),
    }


def _preparation(value: object, output: Path) -> PreparationEvidence:
    data = fields(value, "ready reason log source stage")
    if data["source"] != "campaign":
        raise ValueError("Package preparation must be inherited from campaign")
    log, stage = text(data["log"]), text(data["stage"])
    safe_evidence_path(output, log)
    if stage not in ("started", "sources_retained", "initial_verified"):
        raise ValueError("Invalid preparation stage")
    return {
        "source": "campaign",
        "ready": _boolean(data["ready"]),
        "reason": _optional_text(data["reason"]),
        "log": log,
        "stage": stage,
    }


def _check_preparation_stage(result: InstallTestResult) -> None:
    stage = result.preparation.get("stage")
    expected = None if stage == "started" else "expected/"
    if result.evidence["expected_contents"] != expected:
        raise ValueError("Preparation stage contradicts retained source reference")
    if result.preparation["ready"] and (
        stage != "initial_verified" or result.preparation["reason"] is not None
    ):
        raise ValueError("Ready preparation requires completed initial verification without reason")


def _check_references(result: InstallTestResult, step: StepEvidence, index: int) -> None:
    command, observations = step["command"], step["observations"]
    assert command is not None and observations is not None
    references = [
        *result.evidence.values(),
        *observations.values(),
        command["stdout_file"],
        command["stderr_file"],
    ]
    if result.status == "passed" and any(reference is None for reference in references):
        raise ValueError("passed requires all evidence references")
    expected = {
        "before": f"steps/{index}/before.json",
        "after": f"steps/{index}/after.json",
        "stdout_file": f"steps/{index}/stdout.txt",
        "stderr_file": f"steps/{index}/stderr.txt",
    }
    actual = {
        **observations,
        "stdout_file": command["stdout_file"],
        "stderr_file": command["stderr_file"],
    }
    if any(value is not None and value != expected[key] for key, value in actual.items()):
        raise ValueError("Evidence references must belong to their own step")


def _check_skipped(step: StepEvidence) -> None:
    if (
        step["progress"] != "not_started"
        or "failure" in step
        or step["skip_reason"] is None
        or any(step[key] is not None for key in ("command", "verification", "observations"))
    ):
        raise ValueError("An unattempted step requires a reason and no command or observations")


def _check_attempted(step: StepEvidence) -> str:
    command, verification = step["command"], step["verification"]
    if step["progress"] == "not_started":
        raise ValueError("Attempted step cannot be declared not started")
    if step["skip_reason"] is not None:
        raise ValueError("An attempted step cannot have a skip reason")
    if command is None or verification is None or step["observations"] is None:
        if step["progress"] == "incomplete":
            return "incomplete"
        raise ValueError("A finished step requires command, verification and observations")
    if step["progress"] == "finished" and (
        command["state"] != "completed" or not verification.complete
    ):
        raise ValueError("Finished step requires complete command and verification")
    if (
        step["progress"] == "incomplete"
        or command["state"] != "completed"
        or not verification.complete
    ):
        return "incomplete"
    if command["exit_code"] != 0 or verification.mismatches:
        return "failed"
    return "passed"


def _check_next_step(result: InstallTestResult, step: StepEvidence, index: int) -> str:
    if "failure" in step:
        return _check_failed_phase(step)
    status = _check_attempted(step)
    if step["command"] is not None and step["observations"] is not None:
        _check_references(result, step, index)
    return status


def _check_failed_phase(step: StepEvidence) -> str:
    if step["progress"] != "incomplete":
        raise ValueError("Failed execution stage must be incomplete")
    failure = step.get("failure")
    assert failure is not None
    stage = failure["stage"]
    before_command = {"preparation", "expectations", "command"}
    after_command = {"command_evidence", "observation", "verification", "verification_evidence"}
    if stage not in before_command | after_command:
        raise ValueError("Unknown failed execution stage")
    if stage in before_command:
        if step["command"] is not None or step["skip_reason"] != failure["reason"]:
            raise ValueError("Failure before command cannot claim command evidence")
    elif step["command"] is None or step["skip_reason"] is not None:
        raise ValueError("Failure after command requires actual command facts")
    expected_observation = stage in {"verification", "verification_evidence"}
    if (step["observations"] is not None) != expected_observation:
        raise ValueError("Failed stage contradicts retained observations")
    if (step["verification"] is not None) != (stage == "verification_evidence"):
        raise ValueError("Failed stage contradicts retained verification")
    return "incomplete"


def _intermediate_status(intermediate: IntermediateEvidence) -> str:
    verdict = intermediate["verification"]
    if intermediate["progress"] != "finished":
        return "incomplete"
    if verdict is None or not verdict.complete:
        raise ValueError("Finished intermediate preparation requires complete verification")
    return "failed" if verdict.mismatches or verdict.obstacles else "passed"


def _transition_status(result: InstallTestResult, index: int, status: str) -> str:
    if index == 1 and result.intermediate_preparation is not None and status == "passed":
        return _intermediate_status(result.intermediate_preparation)
    return status


def _check_consistency(result: InstallTestResult) -> None:
    _check_preparation_stage(result)
    if not result.preparation["ready"]:
        for step in result.steps:
            _check_skipped(step)
        if result.status != "not_run" or result.preparation["reason"] is None:
            raise ValueError("Unavailable preparation requires not_run and a reason")
        return
    status = "passed"
    for index, step in enumerate(result.steps):
        status = _transition_status(result, index, status)
        if status != "passed":
            _check_skipped(step)
            continue
        if step["progress"] == "not_started":
            _check_skipped(step)
            status = "incomplete"
        else:
            status = _check_next_step(result, step, index)

    if result.status != status:
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
    if [step["operation"] for step in steps] != case.operations:
        raise ValueError("Result steps do not match the requested operations")
    result = InstallTestResult(
        expected,
        _preparation(data["preparation"], output_directory),
        steps,
        status,
        {
            key: _evidence(value, output_directory)
            for key, value in fields(data["evidence"], "journal expected_contents").items()
        },
    )
    result.intermediate_preparation = _intermediate(
        data["intermediate_preparation"], output_directory
    )
    if (result.intermediate_preparation is None) != (case.intermediate_preparation is None):
        raise ValueError("Intermediate evidence contradicts case definition")
    _check_consistency(result)
    check_effect_result(result, case, output_directory)
    return result


def read_evidence(output_directory: Path) -> InstallTestResult:
    """Rebuild and validate verdicts entirely from retained native evidence."""
    if _read_json_evidence(output_directory, "evidence-format.json") != {
        "format": "explicit-expectations-v3"
    }:
        raise ValueError("Unsupported evidence format; use its identified historical reader")
    case = EffectInstallCase.from_json(
        safe_evidence_path(output_directory, "case.json").read_text(encoding="utf-8")
    )
    return _read_result(output_directory, case)
