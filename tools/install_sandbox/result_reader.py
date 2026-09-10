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
    if step["skip_reason"] is None or any(
        step[key] is not None for key in ("command", "verification", "observations")
    ):
        raise ValueError("An unattempted step requires a reason and no command or observations")


def _check_attempted(step: StepEvidence) -> str:
    command, verification = step["command"], step["verification"]
    if step["skip_reason"] is not None:
        raise ValueError("An attempted step cannot have a skip reason")
    if command is None or verification is None or step["observations"] is None:
        raise ValueError("An attempted case requires command, verification and observations")
    if command["state"] != "completed" or not verification.complete:
        return "incomplete"
    if command["exit_code"] != 0 or verification.mismatches:
        return "failed"
    return "passed"


def _check_consistency(result: InstallTestResult) -> None:
    if not result.preparation["ready"]:
        for step in result.steps:
            _check_skipped(step)
        if result.status != "not_run" or result.preparation["reason"] is None:
            raise ValueError("Unavailable preparation requires not_run and a reason")
        return
    status = "passed"
    for index, step in enumerate(result.steps):
        if status != "passed":
            _check_skipped(step)
            continue
        status = _check_attempted(step)
        _check_references(result, step, index)
    if result.status != status:
        raise ValueError("Case status contradicts command or verification facts")


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
    return result
