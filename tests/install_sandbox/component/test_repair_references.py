"""Reference repair through the coordinator, controlled processes and real verification."""

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
_REFS = ".sandbox-reference/skills/graphify/references/"
_SOURCE = "graphify/skills/claude/references/"
_SECOND = b"Reference two.\x00\xff\n"
_THIRD = b"Reference three.\n"


def _script(mode: str) -> str:
    base = controlled_script("passed")
    install = (
        base
        + f"\nPath({_REFS + 'sub'!r}).mkdir(exist_ok=True)\n"
        + (
            f"Path({_REFS + 'sub/two.md'!r}).write_bytes({_SECOND!r})\n"
            f"Path({_REFS + 'z.md'!r}).write_bytes({_THIRD!r})\n"
        )
    )
    second = {
        "absent": "pass",
        "partial_deleted": f"Path({_REFS + 'one.md'!r}).write_bytes(b'Reference one.\\n')",
        "partial_altered": f"Path({_REFS + 'sub/two.md'!r}).write_bytes({_SECOND!r})",
        "nonzero": "raise SystemExit(7)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
        "timeout": "import time; time.sleep(30)",
        "version": install + "Path('.sandbox-reference/skills/graphify/.graphify_version')"
        ".write_text('Other version')",
        "backup": install
        + "Path('.sandbox-reference/skills/graphify/SKILL.md.bak').write_text('Backup')",
        "home": install + "Path(os.environ['HOME'], 'extra.txt').write_text('Extra')",
        "extra_reference": install + f"Path({_REFS + 'extra.md'!r}).write_text('Extra')",
    }.get(mode, install)
    first = "raise SystemExit(9)" if mode == "first_failure" else install
    if mode == "not_started":
        first += "Path(sys.argv[0]).unlink()\n"
    return (
        base.splitlines()[0] + "\nimport os, sys\nfrom pathlib import Path\n"
        "counter = Path(os.environ['TMPDIR']) / 'attempts'\n"
        "number = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(number + 1))\n"
        "print(f'installation {number}', flush=True)\n"
        f"exec({first!r} if number == 0 else {second!r})\n"
    )


def arrange_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "passed") -> None:
    LocalCase(tmp_path)
    (tmp_path / "case.json").unlink()
    for name, content in (("sub/two.md", _SECOND), ("z.md", _THIRD)):
        path = tmp_path / "subject" / _SOURCE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    executable = tmp_path / "controlled-installer"
    executable.write_text(_script(mode), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT / "controlled_repair_case.py"))
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_repair(tmp_path: Path) -> CoordinatedResult:
    return InstallTestCoordinator().run_case(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_name="repair-references",
        subject_checkout=tmp_path / "subject",
        case_file=tmp_path / "case.json",
        output_directory=tmp_path / "results",
        runtime_executable=_COMPONENT / "fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )


def _read(tmp_path: Path):
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    return read_result(tmp_path / "results", case)


def test_repair_preserves_three_distinct_states_and_sources_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    source_before = {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    result = run_repair(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    assert source_before == {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    assert (tmp_path / "work/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert (output / "preparation.log").read_text().count("controlled package preparation") == 2
    first, second = result.test.steps
    assert first["command"] is not None and second["command"] is not None
    assert first["command"]["args"] == second["command"]["args"]
    assert first["command"]["cwd"] == second["command"]["cwd"]
    prep = second.get("preparation")
    assert prep is not None and prep["ready"]
    assert "deleted_path" in prep["plan"]
    assert prep["plan"]["deleted_path"] == _REFS + "one.md"
    assert prep["plan"]["altered_path"] == _REFS + "sub/two.md"
    for phase in ("steps/0/after", "steps/1/before", "steps/1/after"):
        altered = (output / phase / "project" / _REFS / "sub/two.md").read_bytes()
        assert altered == _SECOND + (
            b"\nSandbox repair witness.\n" if phase.endswith("before") else b""
        )
        assert (output / phase / "project" / _REFS / "z.md").read_bytes() == _THIRD
    before = json.loads((output / "steps/1/before.json").read_bytes())
    assert not any(e["path"] == _REFS + "one.md" for e in before["entries"])
    assert (output / "expected" / _SOURCE / "sub/two.md").read_bytes() == _SECOND
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert _read(tmp_path) == result.test


@pytest.mark.parametrize(
    "mode, status, mismatch",
    [
        ("absent", "failed", "missing_file"),
        ("partial_deleted", "failed", "content_mismatch"),
        ("partial_altered", "failed", "missing_file"),
        ("nonzero", "failed", "missing_file"),
        ("signal", "incomplete", "missing_file"),
        ("timeout", "incomplete", "missing_file"),
        ("not_started", "incomplete", "missing_file"),
        ("version", "failed", "version_changed"),
        ("backup", "failed", "unexpected_entry"),
        ("home", "failed", "unexpected_change"),
        ("extra_reference", "failed", "unexpected_reference"),
    ],
)
def test_incorrect_or_interrupted_repair_retains_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    mismatch: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch, mode)
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    step = result.test.steps[1]
    verification = step["verification"]
    assert verification is not None and verification.complete
    assert mismatch in {m.type for m in verification.mismatches}
    assert (tmp_path / "results/steps/1/after.json").exists()
    assert _read(tmp_path) == result.test


@pytest.mark.parametrize(
    "mode",
    [
        "delete_failure",
        "write_failure",
        "wrong_content",
        "no_delete",
        "extra_change",
        "extra_reference",
        "unreadable",
    ],
)
def test_preparation_failure_stops_repair_and_retains_partial_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_REPAIR_PREPARATION", mode)
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "incomplete" and not result.passed
    assert (tmp_path / "work/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None and step["observations"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    verification = prep["verification"]
    assert verification.obstacles if mode == "unreadable" else verification.mismatches
    assert verification.complete == (mode != "unreadable")
    assert (tmp_path / "results/steps/1/before.json").exists()
    assert not (tmp_path / "results/steps/1/stdout.txt").exists()
    if mode == "write_failure":
        assert (
            tmp_path / "results/steps/1/before/project" / _REFS / "sub/two.md"
        ).read_bytes() == b"Partial preparation write\n"
    assert _read(tmp_path) == result.test


@pytest.mark.parametrize("count", [0, 1])
def test_insufficient_sources_prevents_both_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    arrange_repair(tmp_path, monkeypatch)
    sources = tmp_path / "subject" / _SOURCE
    shutil.rmtree(sources / "sub")
    (sources / "z.md").unlink()
    if count == 0:
        (sources / "one.md").unlink()
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None
    assert result.test.status == "not_run"
    assert "at least two" in (result.test.preparation["reason"] or "")
    assert not (tmp_path / "work/command-tmp/attempts").exists()
    assert all(s["command"] is None and s["skip_reason"] for s in result.test.steps)


def test_first_failure_prevents_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_repair(tmp_path, monkeypatch, "first_failure")
    result = run_repair(tmp_path)
    assert result.test is not None and result.result_error is None
    assert result.test.status == "failed"
    assert "preparation" not in result.test.steps[1]
    assert not (tmp_path / "results/steps/1").exists()
    assert result.test.steps[1]["skip_reason"]
