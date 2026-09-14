"""Controlled arrangements shared by sandbox behavior tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.host.coordinator import CoordinatedResult, InstallTestCoordinator

_COMPONENT = Path(__file__).parent


_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


SETTINGS = ".sandbox-reference/settings.json"


ENTRY = "skills/graphify/SKILL.md"


PERSONAL = {"theme": "dark", "instructions": ["my-instructions.md", "team-guidelines.md"]}


CONFORMING: dict[str, Any] = {
    "theme": "dark",
    "instructions": ["my-instructions.md", "team-guidelines.md", ENTRY],
}


CONFORMING["hooks"] = {
    "PreToolUse": [
        {
            "matcher": "Bash|Grep",
            "hooks": [{"type": "command", "command": "graphify hook-guard search"}],
        }
    ]
}


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
        runtime_executable=_COMPONENT.parent / "host/fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )
    result = campaign.cases[0].result
    assert result is not None, campaign
    return result
