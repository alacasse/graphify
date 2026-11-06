"""Retained uninstall evidence remains bound to the intended action and expectations."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.uninstall_support import conduct_uninstall
from tools.install_sandbox.host.result_reader import read_evidence


def test_uninstall_replay_rejects_second_command_replaced_with_install(tmp_path: Path) -> None:
    conduct_uninstall(tmp_path)
    path = tmp_path / "proof/result.json"
    data = json.loads(path.read_text())
    args = data["steps"][1]["facts"]["command"]["args"]
    args[1] = "install"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


def test_uninstall_replay_rejects_forged_removal_expectations(tmp_path: Path) -> None:
    conduct_uninstall(tmp_path)
    path = tmp_path / "proof/expectations/uninstall.json"
    data = json.loads(path.read_text())
    data["expectations"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")


def test_uninstall_replay_rejects_expanded_permission_to_remove_personal_files(
    tmp_path: Path,
) -> None:
    conduct_uninstall(tmp_path)
    path = tmp_path / "proof/expectations/uninstall.json"
    data = json.loads(path.read_text())
    data["allowed_removals"].append(["project", ".agents/skills/graphify/personal.txt"])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_evidence(tmp_path / "proof")
