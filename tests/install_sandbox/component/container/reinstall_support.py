"""Controlled arrangements shared by sandbox behavior tests."""

import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.host.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.host.result_reader import safe_evidence_path

_COMPONENT = Path(__file__).parent


_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


SKILL = ".sandbox-reference/skills/graphify/"


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
            f"p = Path({_JSON!r}); import json; data = json.loads(p.read_text()); "
            "data['instructions'].append('skills/graphify/SKILL.md'); "
            "p.write_text(json.dumps(data))"
        ),
        "user_markdown": (
            f"p = Path({_MARKDOWN!r}); p.write_text(p.read_text().replace("
            "'Respond in English.', 'Changed user text.'))"
        ),
        "user_json": f"p = Path({_JSON!r}); p.write_text(p.read_text().replace('dark', 'light'))",
        "user_document": "Path('.sandbox-reference/my-instructions.md').unlink()",
        "version": f"Path({SKILL + '.graphify_version'!r}).write_text('Changed version\\n')",
        "backup": f"Path({SKILL + 'SKILL.md.bak'!r}).write_text('Unwanted backup\\n')",
        "skill": f"Path({SKILL + 'SKILL.md'!r}).write_text('Wrong skill\\n')",
        "reference": f"Path({SKILL + 'references/one.md'!r}).write_text('Wrong reference\\n')",
        "missing_reference": f"Path({SKILL + 'references/one.md'!r}).unlink()",
        "extra_reference": f"Path({SKILL + 'references/extra.md'!r}).write_text('Extra\\n')",
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
    monkeypatch.setenv(
        "FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT.parent / "container/controlled_case.py")
    )
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_reinstall(tmp_path: Path) -> CoordinatedResult:
    campaign = InstallTestCoordinator().run_campaign(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_names=["reinstall"],
        subject_checkout=tmp_path / "subject",
        output_directory=tmp_path / "campaign",
        runtime_executable=_COMPONENT.parent / "host/fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )
    result = campaign.cases[0].result
    assert result is not None, campaign
    return result


def check_retained_snapshots(output: Path) -> None:
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
        initial = (output / f"steps/0/after/project/{SKILL}{name}").read_bytes()
        assert (output / f"steps/1/before/project/{SKILL}{name}").read_bytes() == initial
        assert (output / f"steps/1/after/project/{SKILL}{name}").read_bytes() == initial
    assert not (output / f"steps/0/before/project/{SKILL}SKILL.md").exists()
