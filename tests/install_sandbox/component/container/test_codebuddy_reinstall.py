"""Two actual install calls with unchanged state between calls and durable evidence."""

import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import CodeBuddyReinstallCase
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.host.result_reader import read_result


def test_codebuddy_reinstall_preserves_bytes_and_bound_commands(tmp_path: Path) -> None:
    local = CodeBuddyReinstallCase(tmp_path)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2
    assert local.calls[0] == local.calls[1]
    assert local.calls[0][0][1:] == ["codebuddy", "install"]
    assert local.first_files == local.repeated_files
    assert len(result.steps) == 2
    assert all(step["verification"] is not None for step in result.steps)
    for relative in (
        "project/.codebuddy/settings.json",
        "project/.codebuddy/settings.json.graphify-bak",
        "project/CODEBUDDY.md",
        "home/.codebuddy/skills/graphify/SKILL.md",
        "home/.codebuddy/skills/graphify/references/one.md",
        "home/.codebuddy/skills/graphify/references/two.md",
        "home/.codebuddy/skills/graphify/.graphify_version",
    ):
        assert (local.output / "steps/0/after" / relative).read_bytes() == (
            local.output / "steps/1/after" / relative
        ).read_bytes()
    backup = local.output / "steps/1/after/project/.codebuddy/settings.json.graphify-bak"
    initial = local.output / "steps/0/before/project/.codebuddy/settings.json"
    assert backup.read_bytes() == initial.read_bytes()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "mode,diagnostic,path",
    [
        ("altered-backup", "content_mismatch", ".codebuddy/settings.json.graphify-bak"),
        ("rolling-backup", "content_mismatch", ".codebuddy/settings.json.graphify-bak"),
        ("missing-backup", "missing_file", ".codebuddy/settings.json.graphify-bak"),
        ("duplicate-hook", "hook_count", ".codebuddy/settings.json"),
        ("duplicate-markdown", "section_count", "CODEBUDDY.md"),
        ("lost-personal", "personal_hook_count", ".codebuddy/settings.json"),
        ("wrong-skill", "content_mismatch", ".codebuddy/skills/graphify/SKILL.md"),
        ("wrong-reference", "content_mismatch", ".codebuddy/skills/graphify/references/one.md"),
        ("wrong-version", "content_mismatch", ".codebuddy/skills/graphify/.graphify_version"),
        ("json-format", "content_mismatch", ".codebuddy/settings.json"),
    ],
)
def test_codebuddy_second_install_detects_corruption(
    tmp_path: Path, mode: str, diagnostic: str, path: str
) -> None:
    local = CodeBuddyReinstallCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    first, repeated = (step["verification"] for step in result.steps)
    assert first is not None and first.complete and not first.mismatches
    assert repeated is not None and repeated.complete and repeated.mismatches
    assert any(m.type == diagnostic and m.path == path for m in repeated.mismatches)
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


def test_codebuddy_first_failure_stops_second_install(tmp_path: Path) -> None:
    local = CodeBuddyReinstallCase(tmp_path, "first-failure")
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 1
    assert result.steps[1]["command"] is None
    assert result.steps[1]["verification"] is None
    assert result.steps[1]["skip_reason"]
    shutil.rmtree(tmp_path / "work")
    assert read_result(local.output, local.retained_case()) == result


def test_codebuddy_second_backup_unreadable_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = CodeBuddyReinstallCase(tmp_path)
    execute = local.execute
    original = Path.read_bytes
    denied = tmp_path / "work/environment/project/.codebuddy/settings.json.graphify-bak"
    state = {"deny": False}

    def install(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute(args, project, environment, timeout)
        state["deny"] = len(local.calls) == 2
        return result

    def read(path: Path) -> bytes:
        if state["deny"] and path == denied:
            raise PermissionError("Controlled second backup read denied")
        return original(path)

    monkeypatch.setattr(local, "execute", install)
    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 2
    verification = result.steps[1]["verification"]
    assert verification is not None and not verification.complete
    assert any("second backup read denied" in o["reason"] for o in verification.obstacles)
    shutil.rmtree(tmp_path / "work")
    assert read_result(local.output, local.retained_case()) == result
