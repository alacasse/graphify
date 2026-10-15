"""Independent altered and duplicate search-hook repair contracts."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import CodeBuddyHookRepairPairCase
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.contracts.results import FileAlterationPlan
from tools.install_sandbox.host.result_reader import read_result

_SETTINGS = ".codebuddy/settings.json"
_CASES = ["repair-altered-json-hook", "repair-duplicate-json-hook"]
_SEARCH = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize("mode", ["passed", "keep-second", "prepend"])
def test_pair_repairs_preserve_witnesses_and_survive_cleanup(
    tmp_path: Path, case_name: str, mode: str
) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name, mode)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2 and local.calls[0] == local.calls[1]
    first = json.loads(local.first_files["project/" + _SETTINGS])
    prepared = json.loads(local.repeated_files["project/" + _SETTINGS])
    if case_name == "repair-altered-json-hook":
        first["hooks"]["PreToolUse"][0]["hooks"][-1]["timeout"] = 11
    else:
        first["hooks"]["PreToolUse"][1]["hooks"].append(_SEARCH)
    assert prepared == first
    assert (
        local.output / "steps/1/after/project" / (_SETTINGS + ".graphify-bak")
    ).read_bytes() == (local.output / "steps/0/before/project" / _SETTINGS).read_bytes()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize(
    "mode",
    [
        "no-op",
        "cross-group-duplicate",
        "lost-second-group",
        "second-group-attribute",
        "lost-second-hook",
        "group-order",
        "read-hook",
        "lost-personal",
        "extra-field",
        "metadata",
        "group-field",
        "order",
        "altered-backup",
        "rolling-backup",
        "missing-backup",
        "wrong-reference",
        "wrong-skill",
        "wrong-version",
        "registry",
    ],
)
def test_pair_rejects_incomplete_repair_and_personal_losses(
    tmp_path: Path, case_name: str, mode: str
) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


def test_adding_conforming_search_does_not_repair_retained_altered_hook(tmp_path: Path) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, _CASES[0], "retain-altered")
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("case_name", _CASES)
def test_pair_first_install_failure_blocks_second_command(tmp_path: Path, case_name: str) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name, "first-failure")
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 1
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize(
    "mode", ["no-change", "personal", "foreign", "wrong-hook", "failure", "unobservable"]
)
def test_pair_preparation_must_be_exact_and_observable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str, mode: str
) -> None:
    original = Environment.prepare_json_hook_repair
    read_bytes = Path.read_bytes
    prepared = False

    def prepare(environment: Environment, plan: FileAlterationPlan) -> str | None:
        nonlocal prepared
        if mode == "no-change":
            return None
        reason = original(environment, plan)
        if mode == "personal":
            path = environment.project / _SETTINGS
            path.write_bytes(path.read_bytes().replace(b'"timeout": 17', b'"timeout": 99'))
        elif mode == "foreign":
            (environment.home / "personal-notes.txt").write_bytes(b"Lost")
        elif mode == "wrong-hook":
            path = environment.project / _SETTINGS
            path.write_bytes(path.read_bytes().replace(b'"timeout": 10', b'"timeout": 12'))
        prepared = True
        return "Controlled preparation failure" if mode == "failure" else reason

    def read(path: Path) -> bytes:
        if (
            mode == "unobservable"
            and prepared
            and path == tmp_path / "work/environment/project" / _SETTINGS
        ):
            raise PermissionError("Controlled pair preparation observation denied")
        return read_bytes(path)

    monkeypatch.setattr(Environment, "prepare_json_hook_repair", prepare)
    monkeypatch.setattr(Path, "read_bytes", read)
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 1 and result.steps[1]["command"] is None
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
@pytest.mark.parametrize("mode", ["missing", "tampered", "forged"])
def test_pair_requires_complete_retained_observations(
    tmp_path: Path, case_name: str, phase: str, mode: str
) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name)
    assert local.run().status == "passed"
    snapshot_file = local.output / (phase + ".json")
    snapshot = json.loads(snapshot_file.read_bytes())
    entry = next(
        e for e in snapshot["entries"] if e["root"] == "project" and e["path"] == _SETTINGS
    )
    path = local.output / entry["content_file"]
    if mode == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_bytes())
        data["metadata"]["owner"] = "forged"
        content = json.dumps(data).encode()
        path.write_bytes(content)
        if mode == "forged":
            entry["sha256"] = hashlib.sha256(content).hexdigest()
            snapshot_file.write_text(json.dumps(snapshot))
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize("missing", [False, True])
def test_pair_requires_independent_preparation_witness(
    tmp_path: Path, case_name: str, missing: bool
) -> None:
    local = CodeBuddyHookRepairPairCase(tmp_path, case_name)
    assert local.run().status == "passed"
    path = local.output / "steps/1/preparation/altered-content.bin"
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"Forged pair witness")
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())


def test_functional_failure_keeps_other_scenario_independent(tmp_path: Path) -> None:
    altered = CodeBuddyHookRepairPairCase(tmp_path / "altered", _CASES[0], "no-op")
    duplicate = CodeBuddyHookRepairPairCase(tmp_path / "duplicate", _CASES[1])
    failed = altered.run()
    passed = duplicate.run()
    assert failed.status == "failed" and passed.status == "passed"
    assert len(altered.calls) == len(duplicate.calls) == 2
    assert altered.calls[0][1] != duplicate.calls[0][1]
    assert altered.calls[0][2]["HOME"] != duplicate.calls[0][2]["HOME"]
    assert read_result(altered.output, altered.retained_case()) == failed
    assert read_result(duplicate.output, duplicate.retained_case()) == passed
