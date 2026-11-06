"""Replay rejects altered stale witnesses and destinations after the workspace is gone."""

import base64
import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.stale_references_tmp_support import (
    conduct_stale_references_tmp,
)
from tools.install_sandbox.host.result_reader import read_evidence


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", base64.b64encode(b"Another stale value").decode("ascii")),
        (
            "destination",
            {"root": "project", "path": ".synthetic/skills/package/references.tmp/stale.md"},
        ),
        ("destination", {"root": "home", "path": ".synthetic/skills/package/SKILL.md"}),
    ],
)
def test_stale_references_tmp_replay_rejects_forged_bound_operation(
    tmp_path: Path, field: str, value: object
) -> None:
    conduct_stale_references_tmp(tmp_path)
    operation = tmp_path / "proof/intermediate/operation.json"
    payload = json.loads(operation.read_text())
    payload[field] = value
    operation.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


def test_stale_references_tmp_replay_rejects_tampered_observed_witness(tmp_path: Path) -> None:
    conduct_stale_references_tmp(tmp_path)
    witness = (
        tmp_path / "proof/intermediate/after/home/.synthetic/skills/package/references.tmp/stale.md"
    )
    assert witness.read_bytes() == b"Stale reference.\n"
    witness.write_bytes(b"Another reference.\n")
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")
