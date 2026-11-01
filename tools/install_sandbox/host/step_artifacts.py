"""Inspect every physical step artifact using the shared publication layout."""

import stat
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from tools.install_sandbox.contracts.evidence_layout import (
    ArtifactLocation,
    FilesystemEntry,
    StagedEvidence,
    classify_staging,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.host.evidence_reader import (
    check_snapshot,
    read_json_evidence,
    safe_evidence_path,
)


def inventory(
    output: Path, index: int, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], tuple[StagedEvidence, ...]]:
    """Load final artifacts even when the last publication does not reference them."""
    prefix = f"steps/{index}"
    transports: tuple[tuple[str, Literal["json", "snapshot"]], ...] = (
        ("before.json", "snapshot"),
        ("after.json", "snapshot"),
        ("environment.json", "json"),
        ("verification.json", "json"),
        ("failure.json", "json"),
    )
    descriptors = tuple(
        ArtifactLocation(f"{prefix}/{name}", transport) for name, transport in transports
    ) + tuple(
        ArtifactLocation(f"expectations/{phase}.json", "json")
        for phase in ("initial", "install", "intermediate", "reinstall")
    )
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
            raise ValueError("Step evidence must be a regular file or directory")

    if safe_evidence_path(output, prefix).exists():
        visit(prefix)
    if safe_evidence_path(output, "expectations").exists():
        visit("expectations")
    loaded: dict[str, object] = {}
    referenced: set[str] = set()
    for descriptor in descriptors:
        reference = descriptor.reference
        if not safe_evidence_path(output, reference).exists():
            continue
        if descriptor.transport == "snapshot":
            loaded[reference] = snapshot(output, reference)
            for entry in check_snapshot(output, reference, complete=False):
                content = entry.get("content_file")
                if isinstance(content, str):
                    referenced.add(content)
        else:
            loaded[reference] = read_json_evidence(output, reference)
    known = {f"{prefix}/{name}" for name in ("stdout.txt", "stderr.txt")}
    for reference in known:
        if safe_evidence_path(output, reference).exists():
            loaded[reference] = safe_evidence_path(output, reference).read_bytes()
    staged = classify_staging(tuple(entries), descriptors, referenced, known)
    expectation = f"expectations/{'install' if index == 0 else 'reinstall'}.json"
    return loaded, tuple(
        item
        for item in staged
        if any(owner.startswith(prefix + "/") or owner == expectation for owner in item.owners)
    )
