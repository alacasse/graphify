"""Retained metadata must describe the filesystem kind that was observed."""

from pathlib import Path

import pytest

from tools.install_sandbox.host.evidence_reader import snapshot_entry


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("file", "listing_complete", None),
        ("directory", "content_file", None),
        ("directory", "sha256", "0" * 64),
        ("unknown", "content_file", None),
        ("unknown", "sha256", "0" * 64),
        ("unknown", "listing_complete", False),
        ("other", "content_file", None),
        ("other", "sha256", "0" * 64),
        ("other", "listing_complete", True),
    ],
)
def test_kind_rejects_forbidden_fields(
    tmp_path: Path, kind: str, field: str, value: object
) -> None:
    with pytest.raises(
        ValueError, match=rf"^Snapshot project/settings\.json kind {kind} forbids fields: {field}$"
    ):
        snapshot_entry(
            {"root": "project", "path": "settings.json", "kind": kind, field: value},
            tmp_path,
            "initial.json",
        )


@pytest.mark.parametrize("kind", ["file", "directory", "unknown", "other"])
def test_kind_without_content_remains_valid(tmp_path: Path, kind: str) -> None:
    entry = {"root": "project", "path": "settings.json", "kind": kind}
    assert snapshot_entry(entry, tmp_path, "initial.json") == entry
