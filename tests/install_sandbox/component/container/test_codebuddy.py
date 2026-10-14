"""CodeBuddy contract qualification with controlled effects and retained evidence."""

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.container.codebuddy_support import CodeBuddyCase
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize("mode", ["passed", "extra-field"])
def test_compliant_codebuddy_survives_workspace_and_source_removal(
    tmp_path: Path, mode: str
) -> None:
    local = CodeBuddyCase(tmp_path, mode)
    result = local.run()
    assert result.status == "passed", result
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result
    assert (
        local.output / "steps/0/after/home/.codebuddy/skills/graphify/SKILL.md"
    ).read_bytes() == b"# Synthetic skill\n"
    assert (
        local.output / "steps/0/after/project/.codebuddy/settings.json.graphify-bak"
    ).read_bytes() == (
        local.output / "steps/0/before/project/.codebuddy/settings.json"
    ).read_bytes()
    assert not (local.output / "managed-hooks-resolution.json").exists()


@pytest.mark.parametrize(
    "mode",
    [
        "wrong-root",
        "missing-hook",
        "duplicate-hook",
        "lost-personal",
        "metadata",
        "order",
        "missing-backup",
        "altered-backup",
        "instructions",
        "registry",
        "wrong-version",
    ],
)
def test_nonconforming_codebuddy_preserves_failed_result(tmp_path: Path, mode: str) -> None:
    local = CodeBuddyCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    verification = result.steps[0]["verification"]
    assert verification is not None and verification.complete and verification.mismatches
    shutil.rmtree(tmp_path / "work")
    assert read_result(local.output, local.retained_case()) == result


def test_host_rejects_wrong_command_without_registry(tmp_path: Path) -> None:
    local = CodeBuddyCase(tmp_path)
    assert local.run().status == "passed"
    document = local.output / "result.json"
    data = cast(dict[str, Any], json.loads(document.read_bytes()))
    data["steps"][0]["command"]["args"][1:] = ["install", "--platform", "codebuddy", "--project"]
    document.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="command"):
        read_result(local.output, local.retained_case())


@pytest.mark.parametrize(
    "relative",
    [
        "steps/0/after/project/.codebuddy/settings.json.graphify-bak",
        "expected/graphifyy.dist-info/METADATA",
        "steps/0/after/home/.codebuddy/skills/graphify/SKILL.md",
    ],
)
def test_host_rejects_lost_retained_bytes_after_cleanup(tmp_path: Path, relative: str) -> None:
    local = CodeBuddyCase(tmp_path)
    assert local.run().status == "passed"
    shutil.rmtree(tmp_path / "work")
    (local.output / relative).unlink()
    with pytest.raises(OSError):
        read_result(local.output, local.retained_case())


def test_unreadable_backup_observation_remains_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = CodeBuddyCase(tmp_path)
    original = Path.read_bytes
    denied = tmp_path / "work/environment/project/.codebuddy/settings.json.graphify-bak"

    def read(path: Path) -> bytes:
        if path == denied:
            raise PermissionError("Controlled backup read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete", result
    verification = result.steps[0]["verification"]
    assert verification is not None and not verification.complete
    assert any(o["reason"] == "Controlled backup read denied" for o in verification.obstacles)
    shutil.rmtree(tmp_path / "work")
    assert read_result(local.output, local.retained_case()) == result


def test_host_rejects_backup_downgraded_to_digest_after_cleanup(tmp_path: Path) -> None:
    local = CodeBuddyCase(tmp_path)
    assert local.run().status == "passed"
    shutil.rmtree(tmp_path / "work")
    snapshot = local.output / "steps/0/after.json"
    data = cast(dict[str, Any], json.loads(snapshot.read_bytes()))
    backup = next(
        entry
        for entry in data["entries"]
        if entry["root"] == "project" and entry["path"] == ".codebuddy/settings.json.graphify-bak"
    )
    del backup["content_file"]
    backup["sha256"] = "0" * 64
    snapshot.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="retained content"):
        read_result(local.output, local.retained_case())


def test_host_rejects_altered_retained_backup_bytes(tmp_path: Path) -> None:
    local = CodeBuddyCase(tmp_path)
    assert local.run().status == "passed"
    shutil.rmtree(tmp_path / "work")
    backup = local.output / "steps/0/after/project/.codebuddy/settings.json.graphify-bak"
    backup.write_bytes(b"Altered retained backup.\n")
    with pytest.raises(ValueError, match="exact initial"):
        read_result(local.output, local.retained_case())


@pytest.mark.parametrize("missing", [False, True])
def test_host_requires_bound_command_environment(tmp_path: Path, missing: bool) -> None:
    local = CodeBuddyCase(tmp_path)
    assert local.run().status == "passed"
    environment = local.output / "steps/0/environment.json"
    if missing:
        environment.unlink()
    else:
        data = cast(dict[str, Any], json.loads(environment.read_bytes()))
        data["HOME"] = str(tmp_path / "wrong-home")
        environment.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())


@pytest.mark.parametrize(
    "content",
    [
        b"Metadata-Version: 2.4\nName: graphifyy\n",
        b"Version: 8.7.6\nVersion: 9.0.0\n",
    ],
)
def test_invalid_version_source_prevents_success(tmp_path: Path, content: bytes) -> None:
    local = CodeBuddyCase(tmp_path)
    (tmp_path / "subject/graphifyy.dist-info/METADATA").write_bytes(content)
    result = local.run()
    assert result.status == "incomplete", result
    verification = result.steps[0]["verification"]
    assert verification is not None and not verification.complete
    assert any(o["path"] == "graphifyy.dist-info/METADATA" for o in verification.obstacles)
    shutil.rmtree(tmp_path / "work")
    assert read_result(local.output, local.retained_case()) == result
