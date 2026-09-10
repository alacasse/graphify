"""Skill repair through the coordinator, literal controlled effects and real verification."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_local_runner import LocalCase, controlled_script
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.result_reader import read_result

_COMPONENT = Path(__file__).parent
_SPECS = Path(__file__).resolve().parents[3] / "tools/install_sandbox/specs/reference"
SKILL = ".sandbox-reference/skills/graphify/SKILL.md"
SOURCE = b"# Local skill\n"
ALTERED = SOURCE + b"\nSandbox skill repair witness.\n"


def _script(mode: str) -> str:
    install = controlled_script("passed")
    backup = f"Path({SKILL + '.bak'!r}).write_bytes({ALTERED!r})\n"
    repaired = install + backup
    second = {
        "absent": "pass",
        "no_backup": install,
        "wrong_backup": install + f"Path({SKILL + '.bak'!r}).write_bytes({SOURCE!r})",
        "only_backup": backup,
        "nonzero": repaired + "raise SystemExit(7)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
        "timeout": "import time; time.sleep(30)",
        "version": repaired + "Path('.sandbox-reference/skills/graphify/.graphify_version')"
        ".write_text('Other version')",
        "home": repaired + "Path(os.environ['HOME'], 'extra.txt').write_text('Extra')",
        "extra_backup": repaired + f"Path({SKILL + '.bak.1'!r}).write_text('Extra')",
        "user_loss": repaired + "Path('.sandbox-reference/my-instructions.md').write_text('Lost')",
        "missing_reference": repaired
        + "Path('.sandbox-reference/skills/graphify/references/one.md').unlink()",
        "duplicate_json": repaired + "Path('.sandbox-reference/settings.json').write_text("
        '\'{"theme":"dark","instructions":["my-instructions.md","skills/graphify/SKILL.md","skills/graphify/SKILL.md"]}\')',
    }.get(mode, repaired)
    first = "raise SystemExit(9)" if mode == "first_failure" else install
    if mode == "first_backup":
        first += backup
    if mode == "not_started":
        first += "Path(sys.argv[0]).unlink()\n"
    return (
        install.splitlines()[0] + "\nimport os, sys\nfrom pathlib import Path\n"
        "counter = Path(os.environ['TMPDIR']) / 'attempts'\n"
        "number = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(number + 1))\n"
        "print(f'installation {number}', flush=True)\n"
        f"exec({first!r} if number == 0 else {second!r})\n"
    )


def arrange_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "passed") -> None:
    LocalCase(tmp_path)
    (tmp_path / "case.json").unlink()
    executable = tmp_path / "controlled-installer"
    executable.write_text(_script(mode), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv(
        "FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT / "controlled_skill_repair_case.py")
    )
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_skill(tmp_path: Path) -> CoordinatedResult:
    campaign = InstallTestCoordinator().run_campaign(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_names=["repair-skill"],
        subject_checkout=tmp_path / "subject",
        output_directory=tmp_path / "campaign",
        runtime_executable=_COMPONENT / "fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )
    result = campaign.cases[0].result
    assert result is not None, campaign
    return result


def test_skill_and_backup_proofs_survive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_skill(tmp_path, monkeypatch)
    original = {str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()}
    result = run_skill(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    assert original == {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    assert (tmp_path / "work/repair-skill/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    assert (output / "steps/0/after/project" / SKILL).read_bytes() == SOURCE
    assert (output / "steps/1/before/project" / SKILL).read_bytes() == ALTERED
    assert (output / "steps/1/after/project" / SKILL).read_bytes() == SOURCE
    assert (output / "steps/1/after/project" / (SKILL + ".bak")).read_bytes() == ALTERED
    assert (output / "steps/1/preparation/altered-content.bin").read_bytes() == ALTERED
    assert (output / "expected/graphify/skill.md").read_bytes() == SOURCE
    prep = result.test.steps[1].get("preparation")
    assert prep is not None and prep["ready"] and "deleted_path" not in prep["plan"]
    for phase in ("steps/0/after", "steps/1/before"):
        snapshot = json.loads((output / (phase + ".json")).read_bytes())
        assert not any(e["path"] == SKILL + ".bak" for e in snapshot["entries"])
    case = InstallTestCase.from_json((tmp_path / "campaign/inputs/repair-skill.json").read_text())
    shutil.rmtree(tmp_path / "work/repair-skill")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case) == result.test


@pytest.mark.parametrize(
    "mode,status,mismatch",
    [
        ("absent", "failed", "content_mismatch"),
        ("only_backup", "failed", "content_mismatch"),
        ("no_backup", "failed", "missing_file"),
        ("wrong_backup", "failed", "content_mismatch"),
        ("nonzero", "failed", None),
        ("signal", "incomplete", "missing_file"),
        ("timeout", "incomplete", "missing_file"),
        ("not_started", "incomplete", "missing_file"),
        ("version", "failed", "version_changed"),
        ("home", "failed", "unexpected_change"),
        ("extra_backup", "failed", "unexpected_change"),
        ("user_loss", "failed", "unexpected_change"),
        ("missing_reference", "failed", "missing_file"),
        ("duplicate_json", "failed", "json_entry_count"),
    ],
)
def test_incorrect_repair_retains_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    mismatch: str | None,
) -> None:
    arrange_skill(tmp_path, monkeypatch, mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    verification = result.test.steps[1]["verification"]
    assert verification is not None and verification.complete
    assert not verification.obstacles
    if mismatch:
        assert mismatch in {m.type for m in verification.mismatches}
    else:
        assert not verification.mismatches
    assert (tmp_path / "campaign/cases/repair-skill/steps/1/after.json").exists()


@pytest.mark.parametrize(
    "mode",
    ["write_failure", "wrong_content", "no_change", "extra_change", "backup_created", "unreadable"],
)
def test_bad_preparation_blocks_second_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_skill(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_SKILL_PREPARATION", mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "incomplete"
    assert (tmp_path / "work/repair-skill/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None and step["observations"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    assert prep["verification"].complete == (mode != "unreadable")
    assert (
        prep["verification"].obstacles if mode == "unreadable" else prep["verification"].mismatches
    )
    assert not (tmp_path / "campaign/cases/repair-skill/steps/1/stdout.txt").exists()
    if mode == "write_failure":
        assert (
            tmp_path / "campaign/cases/repair-skill/steps/1/before/project" / SKILL
        ).read_bytes() == b"Partial skill write\n"


@pytest.mark.parametrize("mode", ["first_failure", "first_backup"])
def test_first_failure_prevents_alteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_skill(tmp_path, monkeypatch, mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "failed" and not result.passed
    assert "preparation" not in result.test.steps[1]
    assert not (tmp_path / "campaign/cases/repair-skill/steps/1").exists()


def test_unreadable_backup_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arrange_skill(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_SKILL_PREPARATION", "backup_unreadable")
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "incomplete"
    verification = result.test.steps[1]["verification"]
    assert verification is not None and not verification.complete
    assert any(o["path"] == SKILL + ".bak" for o in verification.obstacles)
