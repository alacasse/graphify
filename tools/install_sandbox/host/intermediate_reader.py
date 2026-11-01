"""Load confined retained artifacts and delegate preparation semantics to the protocol."""

import stat
from collections.abc import Callable
from pathlib import Path

from tools.install_sandbox.contracts.evidence_layout import (
    ArtifactLocation,
    FilesystemEntry,
    StagedEvidence,
    classify_staging,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.evidence_reader import (
    check_snapshot,
    read_json_evidence,
    safe_evidence_path,
)
from tools.install_sandbox.rules.repair_actions import ARTIFACTS
from tools.install_sandbox.rules.repair_protocol import Inspection, RepairInputs, inspect


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
) -> tuple[dict[str, object], tuple[StagedEvidence, ...]]:
    entries = _physical_entries(output)
    inventory, referenced = _load_artifacts(output, snapshot)
    known_files = {
        entry.relative
        for entry in entries
        if entry.kind == "file"
        and entry.relative in {"expectations/initial.json", "expectations/install.json"}
    }
    staged = classify_staging(
        entries,
        tuple(ArtifactLocation(item.reference, item.transport) for item in ARTIFACTS),
        referenced,
        known_files,
    )
    return inventory, staged


def _physical_entries(output: Path) -> tuple[FilesystemEntry, ...]:
    entries: list[FilesystemEntry] = []

    def visit(relative: str) -> None:
        path = safe_evidence_path(output, relative)
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            entries.append(FilesystemEntry(relative, "file"))
        elif stat.S_ISDIR(mode):
            entries.append(FilesystemEntry(relative, "directory"))
            for child in sorted(path.iterdir()):
                visit(child.relative_to(output).as_posix())
        else:
            raise ValueError("Preparation evidence must be a regular file or directory")

    for relative in ("intermediate", "expectations"):
        path = safe_evidence_path(output, relative)
        if path.exists():
            if not path.is_dir():
                raise ValueError("Preparation evidence requires a directory")
            visit(relative)
    return tuple(entries)


def _load_artifacts(
    output: Path, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], set[str]]:
    inventory: dict[str, object] = {}
    referenced: set[str] = set()
    for descriptor in ARTIFACTS:
        reference = descriptor.reference
        path = safe_evidence_path(output, reference)
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError("Preparation artifact must be a regular file")
        if descriptor.transport == "snapshot":
            inventory[reference] = descriptor.decode(snapshot(output, reference))
            for entry in check_snapshot(output, reference, complete=False):
                content = entry.get("content_file")
                if isinstance(content, str):
                    referenced.add(content)
        else:
            inventory[reference] = descriptor.decode(read_json_evidence(output, reference))
    return inventory, referenced
