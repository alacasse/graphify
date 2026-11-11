"""Rebuild a campaign from the declaration, host receipts and isolated case evidence."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, cast
from zipfile import ZipFile

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.spec import fields
from tools.install_sandbox.host.campaign_definition import CampaignDefinition, define_campaign
from tools.install_sandbox.host.coordinator import CampaignCase, CampaignResult, CoordinatedResult
from tools.install_sandbox.host.docker_runtime import ContainerRunResult
from tools.install_sandbox.host.evidence_reader import json_list, read_json_evidence
from tools.install_sandbox.host.preparation_reader import read_preparation, retained_inputs
from tools.install_sandbox.host.result_reader import read_evidence


def _require(actual: object, expected: object, location: str) -> None:
    # JSON booleans and numbers must remain distinguishable throughout a proof.
    if json.dumps(actual, sort_keys=True, default=str) != json.dumps(
        expected, sort_keys=True, default=str
    ):
        raise ValueError(f"Campaign evidence disagrees at {location}")


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a campaign evidence object")
    return cast(dict[str, Any], value)


def _container(value: object) -> ContainerRunResult | None:
    if value is None:
        return None
    data = _object(value)
    if type(data.get("cleanup_complete")) is not bool or data.get("state") not in {
        "completed",
        "incomplete",
        "interrupted",
    }:
        raise ValueError("Invalid host runtime receipt")
    return ContainerRunResult(**data)


def _names(path: Path) -> set[str]:
    return {p.name for p in path.iterdir()} if path.is_dir() else set()


def _replay_case(
    root: Path,
    case: EffectInstallCase,
    entry: CampaignCase,
    transport: str,
    record: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    location = f"cases/{case.key.storage_id}"
    output = root / location
    _require(record["output_directory"], "./" + location, location)
    retained = (root / "inputs" / (case.key.storage_id + ".json")).read_text(encoding="utf-8")
    if retained != transport:
        raise ValueError(f"Submitted case does not match declaration: {location}")
    for field in ("state", "not_run_reason", "error"):
        _require(record[field], receipt[field], field)
    entry.state, entry.not_run_reason, entry.error = (
        receipt["state"],
        receipt["not_run_reason"],
        receipt["error"],
    )
    container = _container(receipt["container"])
    if container is None:
        _require(record["result"], None, location)
        if entry.state == "finished" or (output / "result.json").exists():
            raise ValueError(f"Case receipt missing: {location}")
        return
    saved = _object(record["result"])
    _require(saved["container"], receipt["container"], location)
    _require(saved["output_directory"], record["output_directory"], location)
    _require(saved["result_error"], receipt["result_error"], location)
    if entry.state != "finished":
        raise ValueError(f"Unexpected container result: {location}")
    test = None
    if saved["result_error"] is None:
        if (output / "case.json").read_text(encoding="utf-8") != transport:
            raise ValueError(f"Retained case does not match declaration: {location}")
        test = read_evidence(output)
    _require(saved["test"], asdict(test) if test else None, location)
    entry.result = CoordinatedResult(container, test, saved["result_error"], output)


def _replay_entries(
    root: Path,
    definition: CampaignDefinition,
    result: CampaignResult,
    report: dict[str, Any],
    receipts: dict[str, Any],
) -> None:
    cases = {
        case.key: (case, transport)
        for case, transport in zip(definition.built.cases, definition.transports, strict=True)
    }
    ids = {key.storage_id for key in cases}
    _require(sorted(_names(root / "cases")), sorted(ids), "case inventory")
    _require(sorted(_names(root / "inputs")), sorted(i + ".json" for i in ids), "input inventory")
    _require(sorted(receipts), sorted(ids), "host receipts")
    for entry, raw in zip(result.cases, json_list(report["cases"]), strict=True):
        record = _object(raw)
        assert entry.key is not None
        _require(record["key"], entry.key.to_data(), "case key")
        _require(record["name"], entry.name, "operation")
        _require(record["construction"], entry.construction, "construction")
        _require(record["construction_reason"], entry.construction_reason, "construction reason")
        if entry.key in cases:
            _replay_case(
                root,
                cases[entry.key][0],
                entry,
                cases[entry.key][1],
                record,
                _object(receipts[entry.key.storage_id]),
            )
        else:
            _require(record, asdict(entry), "nonconstructible case")


def _replay_preparation(
    root: Path, definition: CampaignDefinition, report: dict[str, Any], result: CampaignResult
) -> None:
    if definition.context.package_root and (root / "preparation" / "result.json").is_file():
        output = root / "preparation"
        result.preparation_result = read_preparation(output)
        if result.preparation_result.status == "prepared":
            _, effects, context = retained_inputs(output)
            if context != definition.context or effects != definition.effects:
                raise ValueError("Prepared package differs from declared campaign inputs")
    expected = result.preparation_result.to_data() if result.preparation_result else None
    _require(report["preparation_result"], expected, "package preparation")
    if (
        definition.context.package_root
        and result.preparation
        and result.preparation.state == "completed"
    ):
        if not result.preparation_result or result.preparation_result.status != "prepared":
            raise ValueError("Completed package preparation has no verified evidence")
        binding = result.preparation_result.binding
        if binding is None or binding["image_id"] != result.preparation.image_id:
            raise ValueError("Prepared image differs from host receipt")
        _verify_case_bindings(result.cases, binding)


def _verify_case_bindings(cases: list[CampaignCase], binding: dict[str, str]) -> None:
    for entry in cases:
        if entry.result is None:
            continue
        if entry.result.container.image_id != binding["image_id"]:
            raise ValueError("Case did not run on the prepared image")
        steps = entry.result.test.steps if entry.result.test else []
        if any(step.command and step.command["args"][0] != binding["executable"] for step in steps):
            raise ValueError("Case did not run the prepared executable")


def replay_directory(root: Path) -> dict[str, Any]:
    definition = define_campaign(read_json_evidence(root, "definition.json"), root)
    result = CampaignResult.from_definition(definition, root)
    report = _object(read_json_evidence(root, "campaign.json"))
    receipts = fields(
        read_json_evidence(root, "host-receipts.json"),
        "interrupted error preparation cleanup cases",
    )
    for field in ("interrupted", "error", "preparation", "cleanup"):
        _require(report[field], receipts[field], field)
    result.interrupted, result.error = report["interrupted"], report["error"]
    result.preparation, result.cleanup = (
        _container(receipts["preparation"]),
        _container(receipts["cleanup"]),
    )
    _replay_entries(root, definition, result, report, _object(receipts["cases"]))
    _replay_preparation(root, definition, report, result)
    derived = result.payload()
    for field in (
        "version",
        "passed",
        "successful",
        "status",
        "scope",
        "scope_results",
        "prepare_only",
        "declared_scopes",
        "selected_keys",
        "executed_keys",
        "omitted_keys",
        "requested_cases",
        "omitted_cases",
        "executed_cases",
        "request",
    ):
        _require(report[field], derived[field], field)
    return report


def replay_campaign(archive: Path) -> dict[str, Any]:
    """Return the verified report from a stand-alone ZIP, without the original subject."""
    with (
        TemporaryDirectory(prefix="install-sandbox-replay-") as temporary,
        ZipFile(archive) as source,
    ):
        root = Path(temporary)
        seen: set[PurePosixPath] = set()
        for info in source.infolist():
            path = PurePosixPath(info.filename)
            if (
                not path.parts
                or path.parts[0] != "evidence"
                or ".." in path.parts
                or path.as_posix() != info.filename.rstrip("/")
                or path in seen
            ):
                raise ValueError("Duplicate or unsafe campaign ZIP entry")
            seen.add(path)
            destination = root / path
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
        return replay_directory(root / "evidence")
