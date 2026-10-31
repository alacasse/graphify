"""Contradictory capture facts cannot masquerade as an honest interruption."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.test_repair_publication_windows import run_stopped
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


@pytest.mark.parametrize("scenario", ["missing-section", "altered-section"])
@pytest.mark.parametrize(
    "contradiction", ["read", "listing", "stat", "foreign", "unjustified-listing"]
)
def test_contradictory_pending_snapshot_is_invalid_after_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, contradiction: str
) -> None:
    run_stopped(tmp_path, monkeypatch, scenario, "intermediate/before.json", "after")
    manifest = tmp_path / "proof/intermediate/before.json"
    data = json.loads(manifest.read_text())
    operation, path = {
        "read": ("read_file", "GUIDE.md"),
        "listing": ("list_directory", "."),
        "stat": ("stat", "GUIDE.md"),
        "foreign": ("read_file", "not-observed.md"),
        "unjustified-listing": ("list_directory", "."),
    }[contradiction]
    if contradiction == "unjustified-listing":
        entry = next(e for e in data["entries"] if e["root"] == "project" and e["path"] == ".")
        entry["listing_complete"] = False
    else:
        data["obstacles"].append(
            {"operation": operation, "root": "project", "path": path, "reason": "Forged failure"}
        )
    manifest.write_text(json.dumps(data))
    with pytest.raises(MalformedEvidence):
        read_evidence(tmp_path / "proof")
