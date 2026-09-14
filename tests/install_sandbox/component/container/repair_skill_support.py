"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.host.coordinator import CoordinatedResult, InstallTestCoordinator

_COMPONENT = Path(__file__).parent


_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


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
        runtime_executable=_COMPONENT.parent / "host/fake_docker.py",
        build_timeout_seconds=10,
        run_timeout_seconds=10,
        graceful_termination_seconds=0.1,
    )
    result = campaign.cases[0].result
    assert result is not None, campaign
    return result
