"""Missing-hook repair preserves the independent witnesses and retained verdict."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import CodeBuddyMissingHookCase
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.contracts.results import FileAlterationPlan
from tools.install_sandbox.host.result_reader import read_result

_SETTINGS = ".codebuddy/settings.json"


@pytest.mark.parametrize("mode", ["passed", "separate-group"])
def test_missing_hook_restoration_and_readback(tmp_path: Path, mode: str) -> None:
    local = CodeBuddyMissingHookCase(tmp_path, mode)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2 and local.calls[0] == local.calls[1]
    first = json.loads((local.output / "steps/0/after/project" / _SETTINGS).read_bytes())
    prepared = json.loads((local.output / "steps/1/before/project" / _SETTINGS).read_bytes())
    deleted = first["hooks"]["PreToolUse"][0]["hooks"].pop()
    assert deleted == {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
    assert prepared == first
    assert prepared["hooks"]["PreToolUse"][0]["hooks"] == [
        {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
    ]
    assert (
        local.output / "steps/1/after/project" / (_SETTINGS + ".graphify-bak")
    ).read_bytes() == (local.output / "steps/0/before/project" / _SETTINGS).read_bytes()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "mode",
    [
        "no-op",
        "duplicate-hook",
        "wrong-hook",
        "malformed-group",
        "read-hook",
        "lost-personal",
        "extra-field",
        "metadata",
        "group-field",
        "order",
        "altered-backup",
        "wrong-reference",
    ],
)
def test_missing_hook_rejects_wrong_restoration(tmp_path: Path, mode: str) -> None:
    local = CodeBuddyMissingHookCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("mode", ["no-change", "personal", "foreign", "failure", "unobservable"])
def test_missing_hook_bad_preparation_blocks_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
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
        prepared = True
        return "Controlled preparation failure" if mode == "failure" else reason

    def read(path: Path) -> bytes:
        if (
            mode == "unobservable"
            and prepared
            and path == tmp_path / "work/environment/project" / _SETTINGS
        ):
            raise PermissionError("Controlled missing-hook observation denied")
        return read_bytes(path)

    monkeypatch.setattr(Environment, "prepare_json_hook_repair", prepare)
    monkeypatch.setattr(Path, "read_bytes", read)
    local = CodeBuddyMissingHookCase(tmp_path)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 1 and result.steps[1]["command"] is None
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
@pytest.mark.parametrize("mode", ["missing", "tampered", "forged"])
def test_missing_hook_requires_retained_truth(tmp_path: Path, phase: str, mode: str) -> None:
    local = CodeBuddyMissingHookCase(tmp_path)
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


@pytest.mark.parametrize("missing", [False, True])
def test_missing_hook_requires_independent_preparation_witness(
    tmp_path: Path, missing: bool
) -> None:
    local = CodeBuddyMissingHookCase(tmp_path)
    assert local.run().status == "passed"
    path = local.output / "steps/1/preparation/altered-content.bin"
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"Forged witness")
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())
