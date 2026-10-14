"""Validate declared CodeBuddy facts at case construction and transport boundaries."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import InstallTestCoordinator

_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/codebuddy-local"


def _payload(tmp_path: Path) -> dict[str, Any]:
    destination = tmp_path / "case.json"
    InstallTestCoordinator().write_case(_SPECS, "codebuddy", destination)
    return cast(dict[str, Any], json.loads(destination.read_bytes()))


def test_declared_command_roots_and_witnesses_survive_case_transport(tmp_path: Path) -> None:
    document = _payload(tmp_path)
    case = InstallTestCase.from_json(json.dumps(document))
    restored = json.loads(case.to_json())
    assert restored == document
    assert restored["spec"]["command"] == ["codebuddy", "install"]
    assert restored["spec"]["destinations"] == {
        "skill": {"root": "home", "path": ".codebuddy/skills/graphify/SKILL.md"},
        "markdown": {"root": "project", "path": "CODEBUDDY.md"},
        "json": {"root": "project", "path": ".codebuddy/settings.json"},
    }
    witnesses = {(file["root"], file["path"]) for file in restored["initial_files"]}
    assert ("project", "CODEBUDDY.md") in witnesses
    assert ("home", ".codebuddy/CODEBUDDY.md") in witnesses
    assert ("project", ".codebuddy/settings.json") in witnesses
    assert ("home", ".codebuddy/settings.json") in witnesses


@pytest.mark.parametrize(
    "command",
    [
        [],
        "codebuddy install",
        ["codebuddy", "uninstall"],
        ["CodeBuddy", "install"],
        ["codebuddy install"],
        ["../codebuddy", "install"],
        ["codebuddy", "install", "--project"],
        ["codebuddy", "--managed-hooks-resolution", "install"],
        ["managed-hooks-resolution", "install"],
        ["codebuddy", 3, "install"],
    ],
)
def test_case_rejects_malformed_or_resolution_injecting_command(
    tmp_path: Path, command: object
) -> None:
    document = _payload(tmp_path)
    document["spec"]["command"] = command
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize("name", ["reinstall", "repair-skill", "repair-json-entry"])
def test_none_mode_rejects_repair_case_before_writing(tmp_path: Path, name: str) -> None:
    destination = tmp_path / "unsupported.json"
    with pytest.raises(ValueError, match="first-install"):
        InstallTestCoordinator().write_case(_SPECS, "codebuddy", destination, case_name=name)
    assert not destination.exists()


@pytest.mark.parametrize("management", [None, "automatic", "", 4])
def test_case_requires_explicit_supported_hook_management(
    tmp_path: Path, management: object
) -> None:
    document = _payload(tmp_path)
    if management is None:
        del document["spec"]["json"]["hook_management"]
    else:
        document["spec"]["json"]["hook_management"] = management
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize("backup", [False, True])
def test_registry_cannot_use_none_mode_json_relaxations(tmp_path: Path, backup: bool) -> None:
    document = _payload(tmp_path)
    config = document["spec"]["json"]
    config["hook_management"] = "registry"
    if backup:
        config["list"] = "instructions"
    else:
        del config["backup"]
    with pytest.raises(ValueError, match="Registry JSON"):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize(
    "root,path",
    [
        ("subject", ".codebuddy/settings.json"),
        ("", ".codebuddy/settings.json"),
        ("home", "../outside"),
        ("project", "/absolute/settings.json"),
        ("home", ".codebuddy/./settings.json"),
        ("project", ".codebuddy\\settings.json"),
    ],
)
def test_case_rejects_invalid_destination_roots_and_paths(
    tmp_path: Path, root: str, path: str
) -> None:
    document = _payload(tmp_path)
    document["spec"]["destinations"]["json"] = {"root": root, "path": path}
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize(
    "path",
    [
        ".codebuddy/skills/graphify/SKILL.md",
        ".codebuddy/skills/graphify/references",
        ".codebuddy/skills/graphify/references/one.md",
        ".codebuddy/skills/graphify/.graphify_version",
        ".codebuddy/skills/graphify/SKILL.md.bak",
    ],
)
def test_case_rejects_overlap_with_skill_effects_and_backup(tmp_path: Path, path: str) -> None:
    document = _payload(tmp_path)
    document["spec"]["destinations"]["markdown"] = {"root": "home", "path": path}
    with pytest.raises(ValueError, match=r"overlap|collid"):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize(
    "suffix",
    [
        ".graphify-bak",
        ".graphify-state.json",
        ".graphify.lock",
        ".graphify-journal.json",
    ],
)
def test_case_rejects_effect_collision_with_json_evidence(tmp_path: Path, suffix: str) -> None:
    document = _payload(tmp_path)
    document["spec"]["destinations"]["markdown"] = {
        "root": "project",
        "path": ".codebuddy/settings.json" + suffix,
    }
    with pytest.raises(ValueError, match="collid"):
        InstallTestCase.from_json(json.dumps(document))


@pytest.mark.parametrize("suffix", ["", "../backup", "/backup", ".bak/child", ".bak.json"])
def test_case_rejects_unsafe_json_backup_suffix(tmp_path: Path, suffix: str) -> None:
    document = _payload(tmp_path)
    document["spec"]["json"]["backup"] = suffix
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(document))
