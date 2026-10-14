"""Literal synthetic CodeBuddy effects through the public sandbox seam."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.coordinator import InstallTestCoordinator

_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/codebuddy-local"
_SKILL = ".codebuddy/skills/graphify"
_SETTINGS = ".codebuddy/settings.json"


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _settings(original: bytes, mode: str) -> bytes:
    data = cast(dict[str, Any], json.loads(original))
    groups = data["hooks"]["PreToolUse"]
    search = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
    read = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}
    if mode == "extra-field":
        search["description"] = "Additional managed metadata"
    groups[0]["hooks"].append(search)
    groups.append({"matcher": "Read|Glob", "hooks": [read]})
    if mode == "missing-hook":
        groups.pop()
    elif mode == "duplicate-hook":
        groups.append({"matcher": "Bash|Grep", "hooks": [search]})
    elif mode == "lost-personal":
        groups[0]["hooks"].pop(0)
    elif mode == "metadata":
        data["metadata"]["owner"] = "changed"
    elif mode == "order":
        data["hooks"]["PostToolUse"][0]["hooks"].reverse()
    elif mode == "instructions":
        data["instructions"] = ["skills/graphify/SKILL.md"]
    return (json.dumps(data, indent=2) + "\n").encode()


@dataclass
class CodeBuddyCase:
    root: Path
    mode: str = "passed"

    def __post_init__(self) -> None:
        for relative, content in {
            "graphify/skill.md": b"# Synthetic skill\n",
            "graphify/always_on/claude-md.md": b"## graphify\nUse the synthetic graph.\n",
            "graphify/skills/claude/references/one.md": b"Synthetic reference one.\n",
            "graphify/skills/claude/references/two.md": b"Synthetic reference two.\n",
            "graphifyy.dist-info/METADATA": (
                b"Metadata-Version: 2.4\nName: graphifyy\nVersion: 8.7.6\n"
            ),
        }.items():
            _write(self.root / "subject" / relative, content)
        self.case = InstallTestCoordinator().write_case(
            _SPECS, "codebuddy", self.root / "case.json", case_name="first-install"
        )

    @property
    def output(self) -> Path:
        return self.root / "results"

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert timeout == 60
        assert args[1:] == ["codebuddy", "install"]
        home = Path(environment["HOME"])
        skill_home = project if self.mode == "wrong-root" else home
        for name, content in {
            "SKILL.md": b"# Synthetic skill\n",
            "references/one.md": b"Synthetic reference one.\n",
            "references/two.md": b"Synthetic reference two.\n",
            ".graphify_version": b"0.0.0" if self.mode == "wrong-version" else b"8.7.6",
        }.items():
            _write(skill_home / _SKILL / name, content)
        settings = project / _SETTINGS
        original = settings.read_bytes()
        if self.mode != "missing-backup":
            _write(
                Path(str(settings) + ".graphify-bak"),
                b"Changed backup.\n" if self.mode == "altered-backup" else original,
            )
        settings.write_bytes(_settings(original, self.mode))
        markdown = project / "CODEBUDDY.md"
        markdown.write_bytes(markdown.read_bytes() + b"\n## graphify\nUse the synthetic graph.\n")
        digest = hashlib.sha256(str(home / _SKILL).encode()).hexdigest()[:16]
        _write(home / f".cache/graphify/skill-locks/{digest}.lock", b"")
        if self.mode == "registry":
            _write(Path(str(settings) + ".graphify-state.json"), b"{}\n")
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"synthetic\n")

    def run(self) -> InstallTestResult:
        return InstallTestRunner(InstallerDriver(self.execute)).run_case(
            reference_sources=self.root / "subject",
            prepared_executable=self.root / "unused-graphify",
            case_file=self.root / "case.json",
            work_directory=self.root / "work",
            output_directory=self.output,
        )

    def retained_case(self) -> InstallTestCase:
        return InstallTestCase.from_json((self.root / "case.json").read_text())
