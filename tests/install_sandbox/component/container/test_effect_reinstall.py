"""Exercise complete native-effect cases through the shared engine and retained evidence."""

import json
import sys
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.effect_case_support import EffectsRun
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.host.result_reader import read_result


@pytest.mark.parametrize("markdown_only", [False, True])
def test_effect_composition_runs_and_rereads_after_cleanup(
    tmp_path: Path,
    markdown_only: bool,
) -> None:
    local = EffectsRun(tmp_path, markdown_only=markdown_only)
    result = local.run()
    assert result.status == "passed", result
    assert local.calls == [["/controlled", "controlled-install"]] * 2
    if markdown_only:
        home = tmp_path / "work/environment/home"
        assert not (home / ".codebuddy/skills").exists()
        assert not (tmp_path / "work/environment/project/.codebuddy/settings.json").exists()
    assert local.reread_after_cleanup() == result


@pytest.mark.parametrize(
    "mode,diagnostic",
    [
        ("wrong-skill", "content_mismatch"),
        ("wrong-reference", "content_mismatch"),
        ("wrong-version", "content_mismatch"),
        ("unwanted-backup", "unexpected_entry"),
        ("missing-lock", "missing_file"),
        ("duplicate-hook", "hook_count"),
        ("missing-hook", "hook_count"),
        ("lost-personal-hook", "user_content_lost"),
        ("rolling-backup", "content_mismatch"),
        ("registry", "unexpected_entry"),
        ("duplicate-markdown", "section_count"),
        ("wrong-markdown", "content_mismatch"),
        ("lost-personal", "user_content_lost"),
        ("command-failure", None),
    ],
)
def test_effect_faults_fail_and_remain_readable(
    tmp_path: Path,
    mode: str,
    diagnostic: str | None,
) -> None:
    local = EffectsRun(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    verification = result.steps[1]["verification"]
    assert verification is not None and verification.complete
    if diagnostic is not None:
        assert any(mismatch.type == diagnostic for mismatch in verification.mismatches)
    else:
        command = result.steps[1]["command"]
        assert command is not None and command["exit_code"] == 7
    assert local.reread_after_cleanup() == result


@pytest.mark.parametrize("mode", ["wrong-markdown", "command-failure"])
def test_first_failure_blocks_dependent_install(tmp_path: Path, mode: str) -> None:
    local = EffectsRun(tmp_path, mode, fail_at=1)
    result = local.run()
    assert result.status == "failed"
    assert len(local.calls) == 1
    assert result.steps[1]["command"] is None
    assert local.reread_after_cleanup() == result


def test_missing_source_blocks_both_installs(tmp_path: Path) -> None:
    local = EffectsRun(tmp_path)
    (tmp_path / "subject/skill.md").unlink()
    result = local.run()
    assert result.status == "not_run"
    assert not local.calls
    assert local.reread_after_cleanup() == result


@pytest.mark.parametrize(
    "relative",
    [
        "case.json",
        "initial-verification.json",
        "expected/skill.md",
        "steps/1/after/project/CODEBUDDY.md",
        "steps/1/verification.json",
        "steps/0/environment.json",
    ],
)
def test_missing_evidence_is_rejected(tmp_path: Path, relative: str) -> None:
    local = EffectsRun(tmp_path)
    assert local.run().status == "passed"
    (local.output / relative).unlink()
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.case)


@pytest.mark.parametrize("relative", ["case.json", "steps/1/after/project/CODEBUDDY.md"])
def test_altered_evidence_is_rejected(tmp_path: Path, relative: str) -> None:
    local = EffectsRun(tmp_path)
    assert local.run().status == "passed"
    path = local.output / relative
    path.write_text(
        path.read_text()
        .replace("controlled", "changed")
        .replace("Use the synthetic graph.", "Changed instructions.")
    )
    with pytest.raises(ValueError):
        read_result(local.output, local.case)


def test_renamed_target_uses_same_effects_and_verdict(tmp_path: Path) -> None:
    local = EffectsRun(tmp_path)
    path = tmp_path / "case.json"
    data = json.loads(path.read_text())
    data["target"] = "another-label"
    path.write_text(json.dumps(data))
    result = local.run()
    assert result.status == "passed"
    assert local.reread_after_cleanup() == result


def test_markdown_only_simulator_subprocess_and_autonomous_readback(tmp_path: Path) -> None:
    local = EffectsRun(tmp_path, markdown_only=True)
    executable = tmp_path / "literal-installer"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "path = Path('CODEBUDDY.md')\n"
        "content = path.read_text()\n"
        "if '## graphify' not in content:\n"
        "    path.write_text(content + '\\n## graphify\\nUse the synthetic graph.\\n')\n"
        "print('controlled installation')\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    result = InstallTestRunner().run_case(
        reference_sources=tmp_path / "subject",
        prepared_executable=executable,
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=local.output,
    )
    assert result.status == "passed", result
    assert all(step["command"] is not None for step in result.steps)
    executable.unlink()
    assert local.reread_after_cleanup() == result
