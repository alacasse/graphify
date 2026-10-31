"""Load confined retained artifacts and delegate preparation semantics to the protocol."""

import re
from collections.abc import Callable
from pathlib import Path

from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.evidence_reader import (
    check_snapshot,
    read_json_evidence,
    safe_evidence_path,
    verification,
)
from tools.install_sandbox.rules.repair_protocol import ARTIFACTS, Inspection, RepairInputs, inspect


def replay_intermediate(
    result: InstallTestResult,
    output: Path,
    inputs: RepairInputs,
    snapshot: Callable[[Path, str], FilesystemSnapshot],
) -> Inspection:
    published = result.intermediate_preparation
    assert published is not None
    inventory, staged = _inventory(output, snapshot)
    return inspect(inputs, published, inventory, staged)


def _inventory(
    output: Path, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], tuple[str, ...]]:
    inventory, referenced = _load_artifacts(output, snapshot)
    staged = _intermediate_files(output, referenced)
    staged.extend(_expectation_files(output))
    return inventory, tuple(staged)


def _load_artifacts(
    output: Path, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], set[str]]:
    inventory: dict[str, object] = {}
    referenced: set[str] = set()
    for kind, reference, _ in ARTIFACTS:
        path = safe_evidence_path(output, reference)
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError("Preparation artifact must be a regular file")
        if kind in {"before", "after"}:
            inventory[reference] = snapshot(output, reference)
            for entry in check_snapshot(output, reference, complete=False):
                content = entry.get("content_file")
                if isinstance(content, str):
                    referenced.add(content)
        else:
            inventory[reference] = _decode(kind, read_json_evidence(output, reference))
    return inventory, referenced


def _decode(kind: str, raw: object) -> object:
    if kind == "operation":
        return BoundMarkdownMutation.from_data(raw)
    if kind == "performed":
        return PerformedMutation.from_data(raw)
    if kind == "verification":
        return verification(raw)
    return ExpectationSet.from_data(raw)


def _snapshot_directory(relative: str) -> bool:
    return relative in {"intermediate/before", "intermediate/after"} or any(
        relative == f"intermediate/{phase}/{root}"
        or relative.startswith(f"intermediate/{phase}/{root}/")
        for phase in ("before", "after")
        for root in ("home", "project")
    )


def _intermediate_files(output: Path, referenced: set[str]) -> list[str]:
    intermediate = safe_evidence_path(output, "intermediate")
    if not intermediate.exists():
        return []
    if not intermediate.is_dir():
        raise ValueError("Preparation evidence requires a directory")
    staged: list[str] = [] if any(intermediate.iterdir()) else ["intermediate/"]
    known = {reference for _, reference, _ in ARTIFACTS}
    for path in intermediate.rglob("*"):
        relative = path.relative_to(output).as_posix()
        safe_evidence_path(output, relative)
        if path.is_dir():
            if not _snapshot_directory(relative):
                raise ValueError("Unknown preparation evidence directory")
            if not any(reference.startswith(relative + "/") for reference in referenced):
                staged.append(relative + "/")
        elif relative not in known and relative not in referenced:
            staged.append(_staged_file(path, relative))
    return staged


def _staged_file(path: Path, relative: str) -> str:
    if not path.is_file():
        raise ValueError("Preparation evidence must be regular")
    if not _temporary(relative) and not any(
        relative.startswith(f"intermediate/{phase}/{root}/")
        for phase in ("before", "after")
        for root in ("home", "project")
    ):
        raise ValueError("Unknown preparation evidence")
    return relative


def _expectation_files(output: Path) -> list[str]:
    directory = safe_evidence_path(output, "expectations")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("Expectations require a directory")
    known = {reference for _, reference, _ in ARTIFACTS}
    known.update({"expectations/initial.json", "expectations/install.json"})
    staged: list[str] = []
    for path in directory.iterdir():
        relative = path.relative_to(output).as_posix()
        safe_evidence_path(output, relative)
        if not path.is_file():
            raise ValueError("Expectation artifact must be regular")
        if relative in known:
            continue
        if not _temporary(relative):
            raise ValueError("Unknown expectation evidence")
        staged.append(relative)
    return staged


def _temporary(relative: str) -> bool:
    path = Path(relative)
    return any(
        path.parent == Path(reference).parent
        and re.fullmatch(
            re.escape("." + Path(reference).name + ".") + r"[A-Za-z0-9_-]+\.tmp", path.name
        )
        is not None
        for _, reference, _ in ARTIFACTS
    )
