"""Literal physical conventions, independent from writer and repair progression."""

import copy
from typing import cast

import pytest

from tools.install_sandbox.contracts.evidence_layout import (
    ArtifactLocation,
    FilesystemEntry,
    StagedEvidence,
    blob_reference,
    classify_staging,
    plan_json,
    plan_snapshot,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry

LOCATIONS = (
    ArtifactLocation("intermediate/operation.json", "json"),
    ArtifactLocation("intermediate/before.json", "snapshot"),
    ArtifactLocation("intermediate/after.json", "snapshot"),
    ArtifactLocation("expectations/reinstall.json", "json"),
)


def test_json_plan_detaches_document_and_names_atomic_temporary() -> None:
    document = {"items": ["original"]}
    plan = plan_json("intermediate/operation.json", document)
    document["items"].append("changed")
    assert plan.reference == "intermediate/operation.json"
    assert plan.document == {"items": ["original"]}
    assert (plan.temporary_prefix, plan.temporary_suffix) == (".operation.json.", ".tmp")


def test_snapshot_plan_replaces_physical_metadata_without_mutating_input() -> None:
    snapshot = FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry,
                {
                    "root": "project",
                    "path": "GUIDE.md",
                    "kind": "file",
                    "content_file": "old/content",
                    "sha256": "old digest",
                },
            ),
            {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
        ],
        contents={("project", "GUIDE.md"): b"abc"},
    )
    original = copy.deepcopy(snapshot)
    plan = plan_snapshot("intermediate/before.json", snapshot)
    assert snapshot == original
    assert plan.blobs == (("intermediate/before/project/GUIDE.md", b"abc"),)
    assert plan.manifest.document == {
        "entries": [
            {
                "root": "project",
                "path": "GUIDE.md",
                "kind": "file",
                "content_file": "intermediate/before/project/GUIDE.md",
                "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            },
            {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
        ],
        "obstacles": [],
    }
    snapshot.entries.clear()
    snapshot.contents.clear()
    assert plan.blobs == (("intermediate/before/project/GUIDE.md", b"abc"),)
    assert cast(dict[str, object], plan.manifest.document)["entries"]


@pytest.mark.parametrize(
    "reference,root,path,expected",
    [
        ("expected.json", "subject", "docs/guide.md", "expected/docs/guide.md"),
        ("steps/1/after.json", "home", ".config/tool", "steps/1/after/home/.config/tool"),
        ("intermediate/after.json", "project", "GUIDE.md", "intermediate/after/project/GUIDE.md"),
    ],
)
def test_blob_bindings(reference: str, root: str, path: str, expected: str) -> None:
    assert blob_reference(reference, root, path) == expected


@pytest.mark.parametrize(
    "reference,root,path",
    [
        ("../before.json", "project", "GUIDE.md"),
        ("intermediate/before.json", "project", "../GUIDE.md"),
        ("intermediate/before.json", "subject", "GUIDE.md"),
        ("expected.json", "home", "GUIDE.md"),
    ],
)
def test_invalid_blob_bindings(reference: str, root: str, path: str) -> None:
    with pytest.raises(ValueError):
        blob_reference(reference, root, path)


def test_shared_parent_and_partial_snapshot_have_typed_owners() -> None:
    staged = classify_staging(
        (
            FilesystemEntry("intermediate", "directory"),
            FilesystemEntry("intermediate/before", "directory"),
            FilesystemEntry("intermediate/before/project", "directory"),
            FilesystemEntry("intermediate/before/project/GUIDE.md", "file"),
            FilesystemEntry("intermediate/.before.json.A_2-z.tmp", "file"),
        ),
        LOCATIONS,
        set(),
        set(),
    )
    assert staged == (
        StagedEvidence(
            "intermediate",
            "directory",
            frozenset(
                {
                    "intermediate/operation.json",
                    "intermediate/before.json",
                    "intermediate/after.json",
                }
            ),
        ),
        StagedEvidence("intermediate/before", "directory", frozenset({"intermediate/before.json"})),
        StagedEvidence(
            "intermediate/before/project", "directory", frozenset({"intermediate/before.json"})
        ),
        StagedEvidence(
            "intermediate/before/project/GUIDE.md",
            "snapshot_blob",
            frozenset({"intermediate/before.json"}),
        ),
        StagedEvidence(
            "intermediate/.before.json.A_2-z.tmp",
            "json_temporary",
            frozenset({"intermediate/before.json"}),
        ),
    )


def test_validated_files_and_their_directories_are_not_staging() -> None:
    assert (
        classify_staging(
            (
                FilesystemEntry("intermediate", "directory"),
                FilesystemEntry("intermediate/before.json", "file"),
                FilesystemEntry("intermediate/before", "directory"),
                FilesystemEntry("intermediate/before/project", "directory"),
                FilesystemEntry("intermediate/before/project/GUIDE.md", "file"),
                FilesystemEntry("expectations", "directory"),
                FilesystemEntry("expectations/initial.json", "file"),
            ),
            LOCATIONS,
            {"intermediate/before/project/GUIDE.md"},
            {"expectations/initial.json"},
        )
        == ()
    )


@pytest.mark.parametrize(
    "entry",
    [
        FilesystemEntry("intermediate/unrelated", "directory"),
        FilesystemEntry("intermediate/before/subject", "directory"),
        FilesystemEntry("intermediate/before/unknown.txt", "file"),
        FilesystemEntry("intermediate/.operation.json..tmp", "file"),
        FilesystemEntry("intermediate/.operation.json.token.other", "file"),
        FilesystemEntry("intermediate/operation.json", "directory"),
        FilesystemEntry("intermediate/../escape", "file"),
    ],
)
def test_unknown_or_incompatible_entries_are_rejected(entry: FilesystemEntry) -> None:
    with pytest.raises(ValueError):
        classify_staging((entry,), LOCATIONS, set(), set())


def test_unreferenced_blob_keeps_its_owner_even_when_manifest_is_present() -> None:
    assert classify_staging(
        (
            FilesystemEntry("intermediate/before.json", "file"),
            FilesystemEntry("intermediate/before/project/extra.txt", "file"),
        ),
        LOCATIONS,
        set(),
        set(),
    ) == (
        StagedEvidence(
            "intermediate/before/project/extra.txt",
            "snapshot_blob",
            frozenset({"intermediate/before.json"}),
        ),
    )
