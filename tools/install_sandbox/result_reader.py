"""Validate the received case result independently of container execution."""

import json
from pathlib import Path
from typing import cast

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.environment import destinations
from tools.install_sandbox.results import (
    CommandEvidence,
    InstallTestResult,
    ObservationObstacle,
    PreparationEvidence,
    ReferenceRepairPlan,
    SkillBackupPlan,
    SkillRepairPlan,
    StepEvidence,
    StepPreparationEvidence,
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
    has_preparation = isinstance(value, dict) and "preparation" in value
    data = fields(
        cast(object, value),
        "operation skip_reason command verification observations"
        + (" preparation" if has_preparation else ""),
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
        "skip_reason": _optional_text(data["skip_reason"]),
        "command": None if data["command"] is None else _command(data["command"], output),
        "verification": None
        if data["verification"] is None
        else _verification(data["verification"]),
        "observations": references,
    }
    if has_preparation:
        step["preparation"] = _step_preparation(data["preparation"], output)
    return step


def _step_plan(value: object) -> ReferenceRepairPlan | SkillRepairPlan | SkillBackupPlan:
    if isinstance(value, dict) and "backup_path" in value:
        data = fields(cast(object, value), "backup_path backup_content_file")
        return {
            "backup_path": relative_path(data["backup_path"]),
            "backup_content_file": relative_path(data["backup_content_file"]),
        }
    return _repair_plan(cast(object, value))


def _repair_plan(value: object) -> ReferenceRepairPlan | SkillRepairPlan:
    has_deleted = isinstance(value, dict) and "deleted_path" in value
    data = fields(
        cast(object, value),
        "altered_path altered_content_file" + (" deleted_path" if has_deleted else ""),
    )
    common: SkillRepairPlan = {
        "altered_path": relative_path(data["altered_path"]),
        "altered_content_file": relative_path(data["altered_content_file"]),
    }
    if has_deleted:
        return {**common, "deleted_path": relative_path(data["deleted_path"])}
    return common


def _step_preparation(value: object, output: Path) -> StepPreparationEvidence:
    data = fields(value, "plan ready reason before verification")
    plan = _step_plan(data["plan"])
    if "backup_content_file" in plan:
        content_file = plan["backup_content_file"]
        expected_file = "steps/1/preparation/backup-content.bin"
    else:
        content_file = plan["altered_content_file"]
        expected_file = "steps/1/preparation/altered-content.bin"
    if content_file != expected_file:
        raise ValueError("Invalid preparation content evidence path")
    if data["before"] != "steps/1/before.json":
        raise ValueError("Invalid preparation observation path")
    safe_evidence_path(output, content_file)
    result: StepPreparationEvidence = {
        "plan": plan,
        "ready": _boolean(data["ready"]),
        "reason": _optional_text(data["reason"]),
        "before": "steps/1/before.json",
        "verification": _verification(data["verification"]),
    }
    verification = result["verification"]
    if result["ready"]:
        if result["reason"] is not None or not verification.complete or verification.mismatches:
            raise ValueError(
                "Ready step preparation requires complete verification without mismatch"
            )
    elif result["reason"] is None:
        raise ValueError("Unavailable step preparation requires a reason")
    return result


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


def _check_next_step(result: InstallTestResult, step: StepEvidence, index: int) -> str:
    preparation = step.get("preparation")
    if preparation is not None and not preparation["ready"]:
        _check_skipped(step)
        if step["skip_reason"] != preparation["reason"]:
            raise ValueError("Step skip reason contradicts preparation")
        return "incomplete"
    status = _check_attempted(step)
    _check_references(result, step, index)
    return status


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
        status = _check_next_step(result, step, index)

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
    _check_step_preparation_evidence(result, case, output_directory)
    return result


def _read_json_evidence(output: Path, relative: str) -> object:
    return json.loads(
        safe_evidence_path(output, relative).read_bytes(), object_pairs_hook=_json_object
    )


def _check_snapshot(
    output: Path, relative: str, *, complete: bool = True
) -> list[dict[str, object]]:
    """Validate inventory and content bindings, without deciding file conformance."""
    data = fields(_read_json_evidence(output, relative), "entries obstacles")
    for obstacle in _list(data["obstacles"]):
        _obstacle(obstacle)
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    prefix = relative.removesuffix(".json")
    for value in _list(data["entries"]):
        entry = _snapshot_entry(value, output, prefix)
        key = (text(entry["root"]), text(entry["path"]))
        if key in seen:
            raise ValueError("Duplicate snapshot entry")
        seen.add(key)
        entries.append(entry)
    if complete:
        _check_complete_snapshot(entries, _list(data["obstacles"]))
    return entries


def _check_complete_snapshot(entries: list[dict[str, object]], obstacles: list[object]) -> None:
    if obstacles or not entries:
        raise ValueError("Complete verification requires observable snapshot evidence")
    for entry in entries:
        kind = entry["kind"]
        if kind == "file" and entry.get("content_file") is None and entry.get("sha256") is None:
            raise ValueError("Complete verification requires file content evidence")
        if kind == "directory" and entry.get("listing_complete") is not True:
            raise ValueError("Complete verification requires complete directory listings")
        if kind not in {"file", "directory"}:
            raise ValueError("Complete verification contradicts unsupported entry")


def _snapshot_entry(value: object, output: Path, prefix: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid snapshot entry")
    entry = cast(dict[str, object], value)
    if not {"root", "path", "kind"} <= entry.keys() or entry.keys() - {
        "root",
        "path",
        "kind",
        "content_file",
        "sha256",
        "listing_complete",
    }:
        raise ValueError("Invalid snapshot entry fields")
    root, path, kind = text(entry["root"]), text(entry["path"]), text(entry["kind"])
    if path != ".":
        relative_path(path)
    if root not in ({"subject"} if prefix == "expected" else {"project", "home"}):
        raise ValueError("Invalid snapshot root")
    if kind not in {"file", "directory", "unknown", "other"}:
        raise ValueError("Invalid snapshot entry kind")
    if "listing_complete" in entry:
        _boolean(entry["listing_complete"])
    _check_content_binding(entry, output, prefix)
    return entry


def _check_content_binding(entry: dict[str, object], output: Path, prefix: str) -> None:
    root, path = entry["root"], entry["path"]
    if entry.get("content_file") is not None:
        binding = f"{prefix}/{path}" if root == "subject" else f"{prefix}/{root}/{path}"
        if entry["content_file"] != binding:
            raise ValueError("Snapshot content must belong to its own observation")
        safe_evidence_path(output, binding).read_bytes()


def _check_step_preparation_evidence(
    result: InstallTestResult, case: InstallTestCase, output: Path
) -> None:
    _check_preparation_location(result, case)
    if case.name not in {"repair-references", "repair-skill", "preserve-skill-backup"}:
        return
    first, second = result.steps
    preparation = second.get("preparation")
    first_passed = first["command"] is not None and _check_attempted(first) == "passed"
    if (preparation is not None) != first_passed:
        raise ValueError("Step preparation must follow a successful first installation")
    if not result.preparation["ready"]:
        return
    sources = _check_snapshot(output, "expected.json")
    _check_snapshot(output, "steps/0/before.json")
    _check_command_evidence(result, output)
    if case.name == "preserve-skill-backup":
        _check_skill_content_evidence(case, output)
    if preparation is None:
        return
    _check_snapshot(output, preparation["before"], complete=preparation["verification"].complete)
    saved = _step_preparation(
        _read_json_evidence(output, "steps/1/preparation/result.json"), output
    )
    if saved != preparation:
        raise ValueError("Step preparation differs from its saved evidence")
    plan = preparation["plan"]
    if _read_json_evidence(output, "steps/1/preparation/plan.json") != plan:
        raise ValueError("Step preparation plan differs from its saved evidence")
    _check_case_preparation_plan(plan, case, output, sources)
    _check_repeated_command(first, second)


def _check_case_preparation_plan(
    plan: ReferenceRepairPlan | SkillRepairPlan | SkillBackupPlan,
    case: InstallTestCase,
    output: Path,
    sources: list[dict[str, object]],
) -> None:
    if case.name == "preserve-skill-backup":
        if "backup_path" not in plan:
            raise ValueError("Backup preservation requires a backup plan")
        _check_skill_backup_plan(plan, case, output)
        return
    if "backup_path" in plan:
        raise ValueError("Unexpected backup preparation plan")
    _check_case_repair_plan(plan, case, output, sources)


def _check_case_repair_plan(
    plan: ReferenceRepairPlan | SkillRepairPlan,
    case: InstallTestCase,
    output: Path,
    sources: list[dict[str, object]],
) -> None:
    if case.name == "repair-skill":
        _check_skill_repair_plan(plan, case, output)
        _check_skill_content_evidence(case, output)
    else:
        if "deleted_path" not in plan:
            raise ValueError("Reference repair requires a deletion")
        _check_repair_plan(plan, case, output, sources)


def _check_command_evidence(result: InstallTestResult, output: Path) -> None:
    if result.evidence != {"journal": "journal.log", "expected_contents": "expected/"}:
        raise ValueError("Prepared step result requires its retained source and journal references")
    for relative in (result.preparation["log"], "journal.log"):
        safe_evidence_path(output, relative).read_bytes()
    for index, step in enumerate(result.steps):
        if step["command"] is None:
            continue
        verification = step["verification"]
        assert verification is not None
        _check_snapshot(output, f"steps/{index}/after.json", complete=verification.complete)
        saved = _verification(_read_json_evidence(output, f"steps/{index}/verification.json"))
        if saved != step["verification"]:
            raise ValueError("Step verification differs from its saved evidence")
        for name in ("stdout_file", "stderr_file"):
            reference = step["command"][name]
            if not isinstance(reference, str):
                raise ValueError("Missing command evidence")
            safe_evidence_path(output, reference).read_bytes()


def _check_repair_plan(
    plan: ReferenceRepairPlan,
    case: InstallTestCase,
    output: Path,
    sources: list[dict[str, object]],
) -> None:
    # Binding to the retained source inventory is transport consistency, not a
    # second installation or degradation verdict on the host.
    source = case.spec.references_source + "/"
    files = sorted(
        text(e["path"])
        for e in sources
        if e["kind"] == "file" and text(e["path"]).startswith(source)
    )

    destination = destinations(case)["references"] + "/"
    if len(files) < 2 or [plan["deleted_path"], plan["altered_path"]] != [
        destination + path[len(source) :] for path in files[:2]
    ]:
        raise ValueError("Repair paths do not match retained source selection")
    content = safe_evidence_path(output, plan["altered_content_file"]).read_bytes()
    if (
        content
        != safe_evidence_path(output, "expected/" + files[1]).read_bytes()
        + b"\nSandbox repair witness.\n"
    ):
        raise ValueError("Altered content is inconsistent with the retained source")


def _check_skill_repair_plan(
    plan: ReferenceRepairPlan | SkillRepairPlan, case: InstallTestCase, output: Path
) -> None:
    if "deleted_path" in plan or plan["altered_path"] != destinations(case)["skill"]:
        raise ValueError("Skill repair path does not match the case")
    source = safe_evidence_path(output, "expected/" + case.spec.skill_source).read_bytes()
    content = safe_evidence_path(output, plan["altered_content_file"]).read_bytes()
    if content != source + b"\nSandbox skill repair witness.\n":
        raise ValueError("Altered skill content is inconsistent with the retained source")


def _check_skill_backup_plan(plan: SkillBackupPlan, case: InstallTestCase, output: Path) -> None:
    if plan["backup_path"] != destinations(case)["skill"] + ".bak":
        raise ValueError("Backup path does not match the case")
    source = safe_evidence_path(output, "expected/" + case.spec.skill_source).read_bytes()
    content = safe_evidence_path(output, plan["backup_content_file"]).read_bytes()
    if content != source + b"\nSandbox previous backup witness.\n":
        raise ValueError("Backup witness is inconsistent with the retained source")


def _check_preparation_location(result: InstallTestResult, case: InstallTestCase) -> None:
    for index, step in enumerate(result.steps):
        if "preparation" in step and (
            case.name not in {"repair-references", "repair-skill", "preserve-skill-backup"}
            or index != 1
        ):
            raise ValueError("Unexpected step preparation")


def _check_repeated_command(first: StepEvidence, second: StepEvidence) -> None:
    if second["command"] is not None:
        assert first["command"] is not None
        if any(first["command"][key] != second["command"][key] for key in ("args", "cwd")):
            raise ValueError(
                "Dependent installation must repeat the first installation command and directory"
            )


def _check_skill_content_evidence(case: InstallTestCase, output: Path) -> None:
    """A skill or backup observed as a readable file must retain its actual bytes."""
    skill = destinations(case)["skill"]
    for relative in ("steps/0/after.json", "steps/1/before.json", "steps/1/after.json"):
        path = safe_evidence_path(output, relative)
        if not path.exists():
            continue  # A blocked preparation has no second command observation.
        snapshot = fields(_read_json_evidence(output, relative), "entries obstacles")
        obstacles = [_obstacle(o) for o in _list(snapshot["obstacles"])]
        for value in _list(snapshot["entries"]):
            entry = _snapshot_entry(value, output, relative.removesuffix(".json"))
            if entry["root"] == "project" and entry["path"] in {skill, skill + ".bak"}:
                _check_retained_skill(entry, obstacles)


def _check_retained_skill(entry: dict[str, object], obstacles: list[ObservationObstacle]) -> None:
    if entry["kind"] != "file" or entry.get("content_file") is not None:
        return
    if not any(o["root"] == "project" and o["path"] == entry["path"] for o in obstacles):
        raise ValueError("Observed skill and backup require retained content, not only a digest")
