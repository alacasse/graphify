"""Two dependent installations through controlled processes and the real verifier."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_local_runner import LocalCase, controlled_script
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.result_reader import read_result, safe_evidence_path

_COMPONENT = Path(__file__).parent
_SPECS = Path(__file__).resolve().parents[3] / "tools/install_sandbox/specs/reference"
_SKILL = ".sandbox-reference/skills/graphify/"
_MARKDOWN = ".sandbox-reference/instructions.md"
_JSON = ".sandbox-reference/settings.json"


def reinstall_script(mode: str = "passed", step: int = 1) -> str:
    # Count in command scratch space, outside the observed project and home.
    # Effects are literals, with no spec interpretation or substituted verdict.
    damage = {
        "duplicate_markdown": (
            f"Path({_MARKDOWN!r}).open('a').write('\\n## graphify\\nUse the graph.\\n')"
        ),
        "duplicate_json": (
            f"p = Path({_JSON!r}); "
            "p.write_text(p.read_text().replace(']}', "
            "',\"skills/graphify/SKILL.md\"]}'))"
        ),
        "user_markdown": (
            f"p = Path({_MARKDOWN!r}); p.write_text(p.read_text().replace("
            "'Respond in English.', 'Changed user text.'))"
        ),
        "user_json": f"p = Path({_JSON!r}); p.write_text(p.read_text().replace('dark', 'light'))",
        "user_document": "Path('.sandbox-reference/my-instructions.md').unlink()",
        "version": f"Path({_SKILL + '.graphify_version'!r}).write_text('Changed version\\n')",
        "backup": f"Path({_SKILL + 'SKILL.md.bak'!r}).write_text('Unwanted backup\\n')",
        "skill": f"Path({_SKILL + 'SKILL.md'!r}).write_text('Wrong skill\\n')",
        "reference": f"Path({_SKILL + 'references/one.md'!r}).write_text('Wrong reference\\n')",
        "missing_reference": f"Path({_SKILL + 'references/one.md'!r}).unlink()",
        "extra_reference": f"Path({_SKILL + 'references/extra.md'!r}).write_text('Extra\\n')",
        "home": "Path(os.environ['HOME'], 'unexpected.txt').write_text('Unexpected\\n')",
        "project": "Path('unexpected.txt').write_text('Unexpected\\n')",
        "nonzero": "raise SystemExit(7)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
    }.get(mode, "pass")
    base = controlled_script("passed")
    return (
        base.splitlines()[0] + "\nimport os, sys\nfrom pathlib import Path\n"
        "counter = Path(os.environ['TMPDIR']) / 'attempts'\n"
        "number = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(number + 1))\n"
        "print(f'installation {number}', flush=True)\n"
        f"exec({base!r})\n"
        f"if number == {step}:\n    exec({damage!r})\n"
    )


def arrange_reinstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, step: int
) -> None:
    LocalCase(tmp_path)
    (tmp_path / "case.json").unlink()
    executable = tmp_path / "controlled-installer"
    executable.write_text(reinstall_script(mode, step), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT / "controlled_case.py"))
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_reinstall(tmp_path: Path) -> CoordinatedResult:
    return InstallTestCoordinator().run_case(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_name="reinstall",
        subject_checkout=tmp_path / "subject",
        case_file=tmp_path / "case.json",
        output_directory=tmp_path / "results",
        runtime_executable=_COMPONENT / "fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )


def test_two_installs_share_preparation_and_preserve_distinct_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, "passed", 1)
    result = run_reinstall(tmp_path)
    assert result.passed and result.test is not None
    first, second = result.test.steps
    assert first["command"] is not None and second["command"] is not None
    assert first["command"]["args"] == second["command"]["args"]
    assert first["command"]["cwd"] == second["command"]["cwd"]
    assert (tmp_path / "work/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert (output / "preparation.log").read_text().count("controlled package preparation") == 2
    for index, step in enumerate(result.test.steps):
        assert step["verification"] is not None and step["verification"].complete
        assert not step["verification"].mismatches and not step["verification"].obstacles
        assert f"installation {index}" in (output / f"steps/{index}/stdout.txt").read_text()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    assert read_result(output, case) == result.test
    _check_retained_snapshots(output)


def _check_retained_snapshots(output: Path) -> None:
    for relative in (
        "expected.json",
        "steps/0/before.json",
        "steps/0/after.json",
        "steps/1/before.json",
        "steps/1/after.json",
    ):
        snapshot = json.loads((output / relative).read_bytes())
        assert not snapshot["obstacles"]
        for entry in snapshot["entries"]:
            if entry.get("content_file"):
                safe_evidence_path(output, entry["content_file"]).read_bytes()
    for name in ("SKILL.md", ".graphify_version", "references/one.md"):
        initial = (output / f"steps/0/after/project/{_SKILL}{name}").read_bytes()
        assert (output / f"steps/1/before/project/{_SKILL}{name}").read_bytes() == initial
        assert (output / f"steps/1/after/project/{_SKILL}{name}").read_bytes() == initial
    assert not (output / f"steps/0/before/project/{_SKILL}SKILL.md").exists()


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "mode, mismatch",
    [
        ("duplicate_markdown", "section_count"),
        ("duplicate_json", "json_entry_count"),
        ("user_markdown", "user_content_lost"),
        ("user_json", "user_content_lost"),
        ("user_document", "unexpected_change"),
        ("backup", "unexpected_entry"),
        ("skill", "content_mismatch"),
        ("reference", "content_mismatch"),
        ("missing_reference", "missing_file"),
        ("extra_reference", "unexpected_reference"),
        ("home", "unexpected_change"),
        ("project", "unexpected_change"),
        ("nonzero", None),
        ("signal", None),
    ],
)
def test_faults_stop_dependents_and_retain_both_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index: int, mode: str, mismatch: str | None
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, mode, index)
    result = run_reinstall(tmp_path)
    assert not result.passed and result.test is not None and result.result_error is None
    assert result.container.state == "completed" and result.container.cleanup_complete
    assert result.test.status == ("incomplete" if mode == "signal" else "failed")
    step = result.test.steps[index]
    assert step["command"] is not None and step["verification"] is not None
    assert step["verification"].complete
    if mismatch:
        assert mismatch in {m.type for m in step["verification"].mismatches}
    else:
        assert step["command"]["exit_code"] != 0
    assert (tmp_path / "work/command-tmp/attempts").read_text() == str(index + 1)
    assert (tmp_path / f"results/steps/{index}/after.json").exists()
    if index == 0:
        assert result.test.steps[1]["command"] is None
        assert "Step 0" in (result.test.steps[1]["skip_reason"] or "")
        assert not (tmp_path / "results/steps/1").exists()


def test_version_change_is_compared_to_first_installation_not_package_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, "version", 1)
    result = run_reinstall(tmp_path)
    assert result.test is not None and result.test.status == "failed"
    verification = result.test.steps[1]["verification"]
    assert verification is not None
    assert "version_changed" in {m.type for m in verification.mismatches}
    output = result.output_directory
    assert (
        output / f"steps/0/after/project/{_SKILL}.graphify_version"
    ).read_text() == "Any version\n"
    assert (
        output / f"steps/1/after/project/{_SKILL}.graphify_version"
    ).read_text() == "Changed version\n"


def test_preparation_failure_skips_both_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_reinstall(tmp_path, monkeypatch, "passed", 1)
    monkeypatch.setenv("CONTROLLED_PREPARATION_FAIL", "1")
    result = run_reinstall(tmp_path)
    assert result.test is not None and result.test.status == "not_run"
    assert result.result_error is None
    for step in result.test.steps:
        assert step["command"] is None and step["verification"] is None
        assert step["observations"] is None and step["skip_reason"]
    assert not (tmp_path / "work/command-tmp/attempts").exists()
