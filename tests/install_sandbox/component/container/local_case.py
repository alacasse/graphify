"""Controlled arrangements shared by sandbox behavior tests."""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.install_sandbox.container.installer import (
    InstallerDriver,
)
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.results import InstallTestResult

_CASE = Path(__file__).resolve().parents[1] / "fixtures" / "first-install.json"


_INITIAL = (
    "# My project\n\n## Language\nRespond in English.\n\n## Changes\nExplain proposed changes.\n"
)


_FILES = {
    ".sandbox-reference/skills/graphify/SKILL.md": "# Local skill\n",
    ".sandbox-reference/skills/graphify/references/one.md": "Reference one.\n",
    ".sandbox-reference/skills/graphify/.graphify_version": "Any version\n",
    ".sandbox-reference/instructions.md": _INITIAL + "\n## graphify\nUse the graph.\n",
}


def settings_script() -> str:
    return (
        "import json\n"
        "p = Path('.sandbox-reference/settings.json')\n"
        "data = json.loads(p.read_text())\n"
        "data['theme'] = 'dark'\n"
        "data['instructions'] = ['my-instructions.md', 'skills/graphify/SKILL.md']\n"
        "groups = data.setdefault('hooks', {}).setdefault('PreToolUse', [])\n"
        "group = next((g for g in groups if g['matcher'] == 'Bash|Grep'), None)\n"
        "if group is None:\n"
        "    group = {'matcher': 'Bash|Grep', 'hooks': []}\n"
        "    groups.append(group)\n"
        "hook = {'type': 'command', 'command': 'graphify hook-guard search'}\n"
        "if hook not in group['hooks']:\n"
        "    group['hooks'].append(hook)\n"
        "p.write_text(json.dumps(data))\n"
    )


def controlled_script(mode: str) -> str:
    effects = dict(_FILES)
    if mode == "missing":
        del effects[".sandbox-reference/skills/graphify/references/one.md"]
    if mode == "no_effects":
        effects = {}
    ending = {
        "nonzero": "raise SystemExit(7)",
        "timeout": "import time; time.sleep(30)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
    }.get(mode, "")
    return (
        f"#!{sys.executable}\nimport os\nfrom pathlib import Path\n"
        f"for name, content in {effects!r}.items():\n"
        "    path = Path(name)\n    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(content, encoding='utf-8')\n"
        + (settings_script() if mode != "no_effects" else "")
        + "print('controlled stdout', flush=True)\n"
        "print('controlled stderr', file=__import__('sys').stderr, flush=True)\n" + ending + "\n"
    )


@dataclass
class LocalCase:
    root: Path
    mode: str = "passed"

    def __post_init__(self) -> None:
        sources = {
            "graphify/skill.md": "# Local skill\n",
            "graphify/always_on/agents-md.md": "## graphify\nUse the graph.\n",
            "graphify/skills/claude/references/one.md": "Reference one.\n",
            "local-untracked.txt": "Local uncommitted content.\n",
        }
        for name, content in sources.items():
            path = self.root / "subject" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        shutil.copyfile(_CASE, self.root / "case.json")

    @property
    def executable(self) -> Path:
        return self.root / "prepared/bin/graphify"

    def prepare_executable(self) -> Path:
        if self.mode != "not_started":
            self.executable.parent.mkdir(parents=True, exist_ok=True)
            self.executable.write_text(controlled_script(self.mode), encoding="utf-8")
            self.executable.chmod(0o755)
        return self.executable

    def run(self, *, timeout: float = 5) -> InstallTestResult:
        return InstallTestRunner(InstallerDriver(timeout=timeout)).run_case(
            reference_sources=self.root / "subject",
            prepared_executable=self.prepare_executable(),
            case_file=self.root / "case.json",
            work_directory=self.root / "work",
            output_directory=self.root / "results",
        )


def deny_read(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == denied:
            raise PermissionError("Controlled read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
