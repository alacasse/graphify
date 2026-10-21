"""Literal simulated installation, independent of effect expectation algorithms."""

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import EffectSpec, MarkdownSectionEffect
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_result

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/codebuddy-effects.yaml"


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@dataclass
class EffectsRun:
    root: Path
    mode: str = "passed"
    markdown_only: bool = False
    fail_at: int = 2
    calls: list[list[str]] = field(default_factory=list[list[str]])

    def __post_init__(self) -> None:
        for path, content in {
            "skill.md": b"# Synthetic skill\n",
            "always_on/claude-md.md": b"## graphify\nUse the synthetic graph.\n",
            "skills/claude/references/one.md": b"Synthetic reference one.\n",
            "skills/claude/references/two.md": b"Synthetic reference two.\n",
            "METADATA": b"Metadata-Version: 2.4\nName: graphifyy\nVersion: 8.7.6\n",
        }.items():
            write_file(self.root / "subject" / path, content)
        spec = EffectSpecReader().read(FIXTURE)
        if self.markdown_only:
            spec = EffectSpec(
                tuple(e for e in spec.effects if isinstance(e, MarkdownSectionEffect))
            )
        context = SubjectContext(
            "literal-controlled-subject-v1",
            ("controlled-install",),
            "METADATA",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        )
        self.case = build_reinstall_case(spec, context)
        self.case.write(self.root / "case.json")

    @property
    def output(self) -> Path:
        return self.root / "results"

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert timeout == 60
        self.calls.append(args)
        mode = self.mode if len(self.calls) == self.fail_at else "passed"
        if mode == "command-failure":
            return InstallerCommandResult(args, str(project), "completed", 7, None)
        home = Path(environment["HOME"])
        if not self.markdown_only:
            self._install_skill(home, mode)
            self._install_json(project, mode)
        self._install_markdown(project, mode)
        if mode == "lost-neighbor":
            (project / "personal-effect-0.txt").write_text("lost", encoding="utf-8")
        return InstallerCommandResult(args, str(project), "completed", 0, None)

    @staticmethod
    def _install_skill(home: Path, mode: str) -> None:
        skill = home / ".codebuddy/skills/graphify"
        for name, content in {
            "SKILL.md": b"# Synthetic skill\n",
            "references/one.md": b"Synthetic reference one.\n",
            "references/two.md": b"Synthetic reference two.\n",
            ".graphify_version": b"8.7.6",
        }.items():
            write_file(skill / name, content)
        corruptions = {
            "wrong-skill": "SKILL.md",
            "wrong-reference": "references/one.md",
            "wrong-version": ".graphify_version",
            "unwanted-backup": "SKILL.md.bak",
        }
        if mode in corruptions:
            write_file(skill / corruptions[mode], b"Wrong content\n")
        digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
        lock = home / f".cache/graphify/skill-locks/{digest}.lock"
        write_file(lock, b"")
        if mode == "missing-lock":
            lock.unlink()

    @staticmethod
    def _install_json(project: Path, mode: str) -> None:
        path = project / ".codebuddy/settings.json"
        backup = path.with_name("settings.json.graphify-bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        data = cast(dict[str, Any], json.loads(path.read_bytes()))
        groups = data["hooks"]["PreToolUse"]
        search = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
        read = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}
        if search not in groups[0]["hooks"]:
            groups[0]["hooks"].append(search)
            groups.append({"matcher": "Read|Glob", "hooks": [read]})
        if mode == "duplicate-hook":
            groups[0]["hooks"].append(search)
        elif mode == "missing-hook":
            groups.pop()
        elif mode == "lost-personal-hook":
            groups[0]["hooks"].pop(0)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if mode == "rolling-backup":
            backup.write_bytes(path.read_bytes())
        if mode == "registry":
            write_file(path.with_name("settings.json.graphify-state.json"), b"{}")

    @staticmethod
    def _install_markdown(project: Path, mode: str) -> None:
        path = project / "CODEBUDDY.md"
        content = path.read_text(encoding="utf-8")
        section = "## graphify\nUse the synthetic graph.\n"
        if "## graphify" not in content or mode == "duplicate-markdown":
            content += "\n" + section
        if mode == "wrong-markdown":
            content = content.replace("Use the synthetic graph.", "Wrong instructions.")
        if mode == "lost-personal":
            content = section
        path.write_text(content, encoding="utf-8")

    def run(self) -> InstallTestResult:
        return InstallTestRunner(InstallerDriver(self.execute)).run_case(
            reference_sources=self.root / "subject",
            prepared_executable=Path("/controlled"),
            case_file=self.root / "case.json",
            work_directory=self.root / "work",
            output_directory=self.output,
        )

    def reread_after_cleanup(self) -> InstallTestResult:
        shutil.rmtree(self.root / "work")
        shutil.rmtree(self.root / "subject")
        (self.root / "case.json").unlink()
        retained = EffectInstallCase.from_json((self.output / "case.json").read_text())
        return read_result(self.output, retained)
