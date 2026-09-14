"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, controlled_script
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.host.result_reader import read_result

_COMPONENT = Path(__file__).parent


_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


REFS = ".sandbox-reference/skills/graphify/references/"


SOURCE = "graphify/skills/claude/references/"


SECOND = b"Reference two.\x00\xff\n"


THIRD = b"Reference three.\n"


def _script(mode: str) -> str:
    base = controlled_script("passed")
    install = (
        base
        + f"\nPath({REFS + 'sub'!r}).mkdir(exist_ok=True)\n"
        + (
            f"Path({REFS + 'sub/two.md'!r}).write_bytes({SECOND!r})\n"
            f"Path({REFS + 'z.md'!r}).write_bytes({THIRD!r})\n"
        )
    )
    second = {
        "absent": "pass",
        "partial_deleted": f"Path({REFS + 'one.md'!r}).write_bytes(b'Reference one.\\n')",
        "partial_altered": f"Path({REFS + 'sub/two.md'!r}).write_bytes({SECOND!r})",
        "nonzero": "raise SystemExit(7)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
        "timeout": "import time; time.sleep(30)",
        "version": install + "Path('.sandbox-reference/skills/graphify/.graphify_version')"
        ".write_text('Other version')",
        "backup": install
        + "Path('.sandbox-reference/skills/graphify/SKILL.md.bak').write_text('Backup')",
        "home": install + "Path(os.environ['HOME'], 'extra.txt').write_text('Extra')",
        "extra_reference": install + f"Path({REFS + 'extra.md'!r}).write_text('Extra')",
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
    for name, content in (("sub/two.md", SECOND), ("z.md", THIRD)):
        path = tmp_path / "subject" / SOURCE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    executable = tmp_path / "controlled-installer"
    executable.write_text(_script(mode), encoding="utf-8")
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(_COMPONENT / "controlled_repair_case.py"))
    monkeypatch.setenv("CONTROLLED_INSTALLER", str(executable))


def run_repair(tmp_path: Path) -> CoordinatedResult:
    campaign = InstallTestCoordinator().run_campaign(
        specs_directory=_SPECS,
        target="sandbox-reference",
        case_names=["repair-references"],
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


def read(tmp_path: Path):
    case = InstallTestCase.from_json(
        (tmp_path / "campaign/inputs/repair-references.json").read_text()
    )
    return read_result(tmp_path / "campaign/cases/repair-references", case)
