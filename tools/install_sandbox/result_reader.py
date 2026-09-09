"""Validate the received case result independently of container execution."""

import json
from pathlib import Path
from typing import cast

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.results import (
    CommandEvidence,
    InstallTestResult,
    ObservationObstacle,
    PreparationEvidence,
    StepEvidence,
    VerificationMismatch,
    VerificationResult,
)
from tools.install_sandbox.spec import fields, relative_path, text


def safe_evidence_path(output_directory: Path, relative: str) -> Path:
    """Resolve a result-relative evidence reference without leaving its directory."""
    relative_path(relative.removesuffix("/"))
    root = output_directory.resolve()
    try:
        destination = (root / relative).resolve()
    except RuntimeError as error:
        raise ValueError(f"Cannot resolve evidence path: {relative!r}") from error
    if not destination.is_relative_to(root) or destination == root:
        raise ValueError(f"Evidence path escapes the result directory: {relative!r}")
    return destination


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"Duplicate result field: {key}")
        data[key] = value
    return data


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return cast(list[object], value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else text(value)


def _evidence(value: object, output: Path) -> str | None:
    result = _optional_text(value)
    if result is not None:
        safe_evidence_path(output, result)
    return result


def _obstacle(value: object) -> ObservationObstacle:
    data = fields(value, "operation root path reason")
    return {
        "operation": text(data["operation"]),
        "root": text(data["root"]),
        "path": text(data["path"]),
        "reason": text(data["reason"]),
    }


def _mismatch(value: object) -> VerificationMismatch:
    data = fields(value, "type root path expected observed")
    return VerificationMismatch(
        text(data["type"]),
        text(data["root"]),
        text(data["path"]),
        _string(data["expected"]),
        _string(data["observed"]),
    )


def _verification(value: object) -> VerificationResult:
    data = fields(value, "complete mismatches obstacles")
    result = VerificationResult(
        _boolean(data["complete"]),
        [_mismatch(item) for item in _list(data["mismatches"])],
        [_obstacle(item) for item in _list(data["obstacles"])],
    )
    if result.complete and result.obstacles:
        raise ValueError("Complete verification cannot contain observation obstacles")
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


def _step(value: object, output: Path) -> StepEvidence:
    data = fields(value, "operation skip_reason command verification observations")
    observations = data["observations"]
    references = (
        None
        if observations is None
        else {
            key: _evidence(value, output)
            for key, value in fields(observations, "before after").items()
        }
    )
    return {
        "operation": text(data["operation"]),
        "skip_reason": _optional_text(data["skip_reason"]),
        "command": None if data["command"] is None else _command(data["command"], output),
        "verification": None
        if data["verification"] is None
        else _verification(data["verification"]),
        "observations": references,
    }


def _preparation(value: object, output: Path) -> PreparationEvidence:
    data = fields(value, "ready reason log")
    log = text(data["log"])
    safe_evidence_path(output, log)
    return {
        "ready": _boolean(data["ready"]),
        "reason": _optional_text(data["reason"]),
        "log": log,
    }


def _check_passed_references(result: InstallTestResult) -> None:
    if result.status != "passed":
        return
    step = result.steps[0]
    command, observations = step["command"], step["observations"]
    if command is None or observations is None:
        raise ValueError("passed requires command and observation references")
    references = [
        *result.evidence.values(),
        *observations.values(),
        command["stdout_file"],
        command["stderr_file"],
    ]
    if any(reference is None for reference in references):
        raise ValueError("passed requires all evidence references")


def _check_consistency(result: InstallTestResult) -> None:
    step = result.steps[0]
    command, verification = step["command"], step["verification"]
    if result.status == "not_run":
        if (
            result.preparation["ready"]
            or any(step[key] is not None for key in ("command", "verification", "observations"))
            or step["skip_reason"] is None
        ):
            raise ValueError("not_run requires preparation unavailable and an unattempted step")
        return
    if not result.preparation["ready"] or step["skip_reason"] is not None:
        raise ValueError("An attempted case requires ready preparation and no skip reason")
    if command is None or verification is None or step["observations"] is None:
        raise ValueError("An attempted case requires command, verification and observations")
    if result.status == "passed" and (
        command["state"] != "completed"
        or command["exit_code"] != 0
        or not verification.complete
        or verification.mismatches
        or verification.obstacles
    ):
        raise ValueError("passed contradicts command or verification facts")
    if result.status == "failed" and (command["state"] != "completed" or not verification.complete):
        raise ValueError("failed requires a completed command and complete verification")


def read_result(output_directory: Path, case: InstallTestCase) -> InstallTestResult:
    """Read a complete result; retain I/O failures and reject incompatible documents."""
    payload = safe_evidence_path(output_directory, "result.json").read_text(encoding="utf-8")
    data = fields(
        json.loads(payload, object_pairs_hook=_json_object),
        "case preparation steps status evidence",
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
    _check_consistency(result)
    _check_passed_references(result)
    return result
