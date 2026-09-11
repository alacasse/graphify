"""Prove registration restoration and personal preservation through real filesystem effects."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_local_runner import LocalCase, controlled_script
from tests.install_sandbox.docker.test_repair_json_entry_docker import check_case
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.result_reader import read_result

_COMPONENT = Path(__file__).parent
_SPECS = Path(__file__).resolve().parents[3] / "tools/install_sandbox/specs/reference"
SETTINGS = ".sandbox-reference/settings.json"
ENTRY = "skills/graphify/SKILL.md"
PERSONAL = {"theme": "dark", "instructions": ["my-instructions.md", "team-guidelines.md"]}
CONFORMING = {"theme": "dark", "instructions": ["my-instructions.md", "team-guidelines.md", ENTRY]}


def _second(mode: str, repaired: str) -> str:
    documents = {
        "duplicate": {"theme": "dark", "instructions": [*CONFORMING["instructions"], ENTRY]},
        "reverse": {
            "theme": "dark",
            "instructions": ["team-guidelines.md", "my-instructions.md", ENTRY],
        },
        "theme": {**CONFORMING, "theme": "light"},
        "lost_personal": {"theme": "dark", "instructions": [ENTRY]},
    }
    if mode in documents:
        return repaired + f"Path({SETTINGS!r}).write_text({json.dumps(documents[mode])!r})"
    changes = {
        "absent": "pass",
        "personal_file": repaired
        + "Path('.sandbox-reference/team-guidelines.md').write_text('Changed')",
        "missing": repaired + f"Path({SETTINGS!r}).unlink()",
        "invalid": repaired + f"Path({SETTINGS!r}).write_text('Invalid JSON')",
        "nonzero": repaired + "raise SystemExit(7)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
        "timeout": "import time; time.sleep(30)",
        "version": repaired + "Path('.sandbox-reference/skills/graphify/.graphify_version')"
        ".write_text('Other version')",
        "home": repaired + "Path(os.environ['HOME'], 'extra.txt').write_text('Extra')",
        "missing_reference": repaired
        + "Path('.sandbox-reference/skills/graphify/references/one.md').unlink()",
    }
    return changes.get(mode, repaired)


def _script(mode: str) -> str:
    install = controlled_script("passed")
    repaired = install + f"Path({SETTINGS!r}).write_text({json.dumps(CONFORMING)!r})\n"
    first = "raise SystemExit(9)" if mode == "first_failure" else repaired
    if mode == "first_loss":
        first += f"Path({SETTINGS!r}).write_text({json.dumps(PERSONAL)!r})\n"
    if mode == "not_started":
        first += "Path(sys.argv[0]).unlink()\n"
    return (
        install.splitlines()[0] + "\nimport os, sys\nfrom pathlib import Path\n"
        "counter = Path(os.environ['TMPDIR']) / 'attempts'\n"
        "number = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(number + 1))\n"
        f"exec({first!r} if number == 0 else {_second(mode, repaired)!r})\n"
    )


def arrange_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "passed") -> None:
    LocalCase(tmp_path)
    (tmp_path / "case.json").unlink()
    executable = tmp_path / "controlled-installer"
    executable.write_text(_script(mode), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv(
        "FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT / "controlled_json_repair_case.py")
    )
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_json(tmp_path: Path) -> CoordinatedResult:
    campaign = InstallTestCoordinator().run_campaign(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_names=["repair-json-entry"],
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


@pytest.mark.parametrize("preparation", ["passed", "format"])
def test_repair_and_personal_values_survive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preparation: str
) -> None:
    arrange_json(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_JSON_PREPARATION", preparation)
    result = run_json(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    check_case(result)
    assert (tmp_path / "work/repair-json-entry/command-tmp/attempts").read_text() == "2"
    case = InstallTestCase.from_json(
        (tmp_path / "campaign/inputs/repair-json-entry.json").read_text()
    )
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(result.output_directory, case) == result.test
    check_case(result)


@pytest.mark.parametrize(
    "mode,status,mismatch",
    [
        ("absent", "failed", "json_entry_count"),
        ("duplicate", "failed", "json_entry_count"),
        ("reverse", "failed", "user_content_lost"),
        ("theme", "failed", "user_content_lost"),
        ("lost_personal", "failed", "user_content_lost"),
        ("personal_file", "failed", "unexpected_change"),
        ("missing", "failed", "missing_file"),
        ("invalid", "failed", "invalid_json"),
        ("nonzero", "failed", None),
        ("signal", "incomplete", "json_entry_count"),
        ("timeout", "incomplete", "json_entry_count"),
        ("not_started", "incomplete", "json_entry_count"),
        ("version", "failed", "version_changed"),
        ("home", "failed", "unexpected_change"),
        ("missing_reference", "failed", "missing_file"),
    ],
)
def test_bad_reinstallation_keeps_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, status: str, mismatch: str | None
) -> None:
    arrange_json(tmp_path, monkeypatch, mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    verification = result.test.steps[1]["verification"]
    assert verification is not None and verification.complete
    if mismatch:
        assert mismatch in {m.type for m in verification.mismatches}
    else:
        assert not verification.mismatches
    assert (result.output_directory / "steps/1/after.json").exists()


@pytest.mark.parametrize(
    "mode",
    [
        "write_failure",
        "invalid",
        "no_change",
        "wrong_entry",
        "reverse",
        "theme",
        "extra_change",
        "read_failure",
        "unreadable",
    ],
)
def test_bad_preparation_blocks_second_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_json(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_JSON_PREPARATION", mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "incomplete" and not result.passed
    assert (tmp_path / "work/repair-json-entry/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    assert prep["verification"].complete == (mode not in {"unreadable", "read_failure"})
    assert prep["verification"].obstacles or prep["verification"].mismatches
    if mode == "write_failure":
        assert (
            result.output_directory / "steps/1/before/project" / SETTINGS
        ).read_bytes() == b'{"theme":'


@pytest.mark.parametrize("mode", ["first_failure", "first_loss"])
def test_first_failure_prevents_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_json(tmp_path, monkeypatch, mode)
    result = run_json(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "failed"
    assert "preparation" not in result.test.steps[1]
    assert not (result.output_directory / "steps/1").exists()
