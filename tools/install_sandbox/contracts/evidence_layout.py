"""Pure publication plans and physical conventions for retained evidence.

The filesystem adapter supplies inspected entries; protocol progression never
enters this module. Staging describes ownership, not permission to proceed.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.contracts.spec import relative_path


@dataclass(frozen=True)
class ArtifactLocation:
    reference: str
    transport: Literal["json", "snapshot"]


@dataclass(frozen=True)
class FilesystemEntry:
    relative: str
    kind: Literal["file", "directory"]


@dataclass(frozen=True)
class JsonPublication:
    reference: str
    document: object
    temporary_prefix: str
    temporary_suffix: str


@dataclass(frozen=True)
class SnapshotPublication:
    blobs: tuple[tuple[str, bytes], ...]
    manifest: JsonPublication


@dataclass(frozen=True)
class StagedEvidence:
    relative: str
    form: Literal["json_temporary", "snapshot_blob", "directory"]
    owners: frozenset[str]


def plan_json(reference: str, document: object) -> JsonPublication:
    """Detach a document and describe its atomic publication temporary."""
    relative_path(reference)
    return JsonPublication(
        reference, copy.deepcopy(document), f".{PurePosixPath(reference).name}.", ".tmp"
    )


def blob_reference(manifest_reference: str, root: str, path: str) -> str:
    """Bind content to its owning observation, including source-only snapshots."""
    relative_path(manifest_reference)
    relative_path(path)
    prefix = manifest_reference.removesuffix(".json")
    if root not in ({"subject"} if prefix == "expected" else {"home", "project"}):
        raise ValueError("Invalid snapshot content root")
    return f"{prefix}/{path}" if root == "subject" else f"{prefix}/{root}/{path}"


def plan_snapshot(reference: str, snapshot: FilesystemSnapshot) -> SnapshotPublication:
    """Plan blobs before a detached manifest, without modifying logical facts."""
    entries: list[SnapshotEntry] = []
    blobs: list[tuple[str, bytes]] = []
    for entry in snapshot.entries:
        retained = entry.copy()
        retained.pop("content_file", None)
        retained.pop("sha256", None)
        key = (entry["root"], entry["path"])
        if key in snapshot.contents:
            content = snapshot.contents[key]
            relative = blob_reference(reference, *key)
            retained["content_file"] = relative
            retained["sha256"] = hashlib.sha256(content).hexdigest()
            blobs.append((relative, content))
        entries.append(retained)
    return SnapshotPublication(
        tuple(blobs), plan_json(reference, {"entries": entries, "obstacles": snapshot.obstacles})
    )


def _blob_owner(relative: str, artifact: ArtifactLocation, *, directory: bool) -> bool:
    if artifact.transport != "snapshot":
        return False
    prefix = artifact.reference.removesuffix(".json")
    if directory and relative == prefix:
        return True
    if prefix == "expected":
        return relative.startswith(prefix + "/")
    return any(
        (directory and relative == f"{prefix}/{root}") or relative.startswith(f"{prefix}/{root}/")
        for root in ("home", "project")
    )


def classify_staging(
    entries: tuple[FilesystemEntry, ...],
    artifacts: tuple[ArtifactLocation, ...],
    referenced_blobs: set[str],
    known_files: set[str],
) -> tuple[StagedEvidence, ...]:
    """Classify inspected entries; reject unknown paths and incompatible types.

    Final artifacts and validated blobs are evidence rather than staging.
    Directories supporting those observed files are structural; other valid
    directories retain all possible artifact owners for the protocol to judge.
    """
    accepted = {artifact.reference for artifact in artifacts} | referenced_blobs | known_files
    observed = {entry.relative for entry in entries if entry.kind == "file"}
    retained = accepted & observed
    staged: list[StagedEvidence] = []
    for entry in entries:
        relative_path(entry.relative)
        relative = entry.relative
        if relative in accepted:
            if entry.kind != "file":
                raise ValueError(f"Evidence must be a regular file: {relative}")
            continue
        if entry.kind == "directory":
            owners = frozenset(
                artifact.reference
                for artifact in artifacts
                if artifact.reference.startswith(relative + "/")
                or _blob_owner(relative, artifact, directory=True)
            )
            if not owners:
                raise ValueError(f"Unknown evidence directory: {relative}")
            if not any(path.startswith(relative + "/") for path in retained):
                staged.append(StagedEvidence(relative, "directory", owners))
            continue
        if entry.kind != "file":
            raise ValueError(f"Evidence must be regular: {relative}")
        path = PurePosixPath(relative)
        temporary_owners = frozenset(
            artifact.reference
            for artifact in artifacts
            if path.parent == PurePosixPath(artifact.reference).parent
            and re.fullmatch(
                re.escape(plan_json(artifact.reference, None).temporary_prefix)
                + r"[A-Za-z0-9_-]+\.tmp",
                path.name,
            )
        )
        blob_owners = frozenset(
            artifact.reference
            for artifact in artifacts
            if _blob_owner(relative, artifact, directory=False)
        )
        owners = temporary_owners | blob_owners
        if len(owners) != 1 or (temporary_owners and blob_owners):
            raise ValueError(f"Unknown or ambiguous evidence staging: {relative}")
        staged.append(
            StagedEvidence(
                relative, "json_temporary" if temporary_owners else "snapshot_blob", owners
            )
        )
    return tuple(staged)
