"""Reject forged managed state and retain failed transaction observations."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.observations_verifier_support import (
    assert_passed,
    scenario,
)
from tests.install_sandbox.component.host.hook_evidence_support import run
from tools.install_sandbox.contracts.managed_json import sidecars
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize("damage", ["extra", "command", "id", "duplicate", "version", "owner"])
def test_registry_requires_exact_independent_effects(tmp_path: Path, damage: str) -> None:
    local = scenario(tmp_path)
    local.effects()
    assert_passed(local.verify())
    path = local.environment.project / sidecars(local.case)["state"]
    state = json.loads(path.read_bytes())
    if damage == "extra":
        state["effects"][0]["content"]["personal"] = True
    elif damage == "command":
        state["effects"][0]["content"]["command"] = "personal command"
    elif damage == "id":
        state["effects"][0]["id"] = "personal"
    elif damage == "duplicate":
        state["effects"].append(state["effects"][0])
    else:
        state[damage] = "invalid"
    path.write_text(json.dumps(state))
    result = local.verify()
    assert result.complete
    assert any(item.type == "managed_registry" for item in result.mismatches)


@pytest.mark.parametrize("name", ["lock", "journal"])
def test_sidecar_effects_are_checked_and_retained(tmp_path: Path, name: str) -> None:
    local = scenario(tmp_path)
    local.effects()
    path = local.environment.project / sidecars(local.case)[name]
    path.write_bytes(b"interrupted transaction bytes")
    result = local.verify()
    assert result.complete and result.mismatches
    retained = local.writer.output_directory / "steps/0/after/project" / sidecars(local.case)[name]
    assert retained.read_bytes() == b"interrupted transaction bytes"


@pytest.mark.parametrize("damage", ["resolution", "state_binding", "lock_digest", "replay"])
def test_host_rejects_incomplete_or_misbound_managed_evidence(tmp_path: Path, damage: str) -> None:
    case, output = run(tmp_path, "reinstall")
    read_result(output, case)
    if damage == "resolution":
        path = output / "managed-hooks-resolution.json"
        value = json.loads(path.read_bytes())
        value["snapshot_sha256"] = "0" * 64
    elif damage == "replay":
        path = output / "result.json"
        value = json.loads(path.read_bytes())
        value["steps"][1]["command"]["args"] = value["steps"][0]["command"]["args"]
    else:
        path = output / "steps/0/after.json"
        value = json.loads(path.read_bytes())
        wanted = sidecars(case)["state" if damage == "state_binding" else "lock"]
        entry = next(item for item in value["entries"] if item["path"] == wanted)
        if damage == "state_binding":
            entry["content_file"] = "steps/1/after/project/" + wanted
        else:
            entry.pop("content_file")
            entry["sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_result(output, case)


def test_inaccessible_registry_is_incomplete_without_false_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = scenario(tmp_path)
    local.effects()
    registry_path = local.environment.project / sidecars(local.case)["state"]
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == registry_path:
            raise PermissionError("controlled inaccessible registry")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.verify()
    assert not result.complete
    assert any(item["path"] == sidecars(local.case)["state"] for item in result.obstacles)
    assert not any(item.type == "missing_file" for item in result.mismatches)


def test_extra_managed_hook_fields_fail_even_with_conforming_registry(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    local.effects()
    path = local.path("json")
    document = json.loads(path.read_bytes())
    document["hooks"]["PreToolUse"][-1]["hooks"][0]["personalized"] = True
    path.write_text(json.dumps(document))
    result = local.verify()
    assert any(item.type == "managed_hook_content" for item in result.mismatches)
    assert not any(item.type in {"hook_count", "managed_registry"} for item in result.mismatches)


def test_transaction_temporary_bytes_retained_without_ownership_exemption(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    local.effects()
    name = sidecars(local.case)["state"] + ".graphify-tmp-" + "a" * 32 + "-witness"
    path = local.environment.project / name
    path.write_bytes(b"interrupted registry write")
    result = local.verify()
    assert result.complete and any(item.path == name for item in result.mismatches)
    retained = local.writer.output_directory / "steps/0/after/project" / name
    assert retained.read_bytes() == b"interrupted registry write"
