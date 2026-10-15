"""Literal synthetic CodeBuddy effects through the public sandbox seam."""

import hashlib
import json
from dataclasses import dataclass, field
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
    search: dict[str, object] = {
        "type": "command",
        "command": "graphify hook-guard search",
        "timeout": 10,
    }
    read = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}
    if mode == "extra-field":
        search["description"] = "Additional managed metadata"
    _append_search(groups[0]["hooks"], search)
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
    case_name: str = "first-install"

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
            _SPECS, "codebuddy", self.root / "case.json", case_name=self.case_name
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
        initial = markdown.read_bytes()
        section = b"## graphify\nUse the synthetic graph.\n"
        markdown.write_bytes(
            initial.replace(b"## graphify\n", section, 1)
            if self.case_name in {"repair-markdown-section", "repair-missing-markdown-section"}
            else initial + b"\n" + section
        )
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


def _tree_bytes(project: Path, home: Path) -> dict[str, bytes]:
    return {
        f"{label}/{path.relative_to(root)}": path.read_bytes()
        for label, root in (("project", project), ("home", home))
        for path in root.rglob("*")
        if path.is_file()
    }


def _reinstall_fault(project: Path, home: Path, mode: str) -> None:
    settings = project / _SETTINGS
    backup = Path(str(settings) + ".graphify-bak")
    replacements = {
        "altered-backup": (backup, b"Changed backup.\n"),
        "rolling-backup": (backup, settings.read_bytes()),
        "wrong-skill": (home / _SKILL / "SKILL.md", b"Wrong skill.\n"),
        "wrong-reference": (home / _SKILL / "references/one.md", b"Wrong reference.\n"),
        "wrong-version": (home / _SKILL / ".graphify_version", b"0.0.0"),
    }
    if mode in replacements:
        _write(*replacements[mode])
    elif mode == "missing-backup":
        backup.unlink()
    elif mode in {"duplicate-hook", "lost-personal", "json-format"}:
        _reinstall_json_fault(settings, mode)
    elif mode == "duplicate-markdown":
        markdown = project / "CODEBUDDY.md"
        markdown.write_bytes(markdown.read_bytes() + b"\n## graphify\nDuplicate.\n")


def _reinstall_json_fault(settings: Path, mode: str) -> None:
    data = cast(dict[str, Any], json.loads(settings.read_bytes()))
    groups = data["hooks"]["PreToolUse"]
    if mode == "duplicate-hook":
        groups[0]["hooks"].append(dict(groups[0]["hooks"][-1]))
    elif mode == "lost-personal":
        groups[0]["hooks"].pop(0)
    settings.write_text(json.dumps(data, indent=4))


@dataclass
class CodeBuddyReinstallCase(CodeBuddyCase):
    case_name: str = "reinstall"
    calls: list[tuple[list[str], Path, dict[str, str], float]] = field(
        default_factory=list[tuple[list[str], Path, dict[str, str], float]]
    )
    first_files: dict[str, bytes] = field(default_factory=dict[str, bytes])
    repeated_files: dict[str, bytes] = field(default_factory=dict[str, bytes])

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        self.calls.append((list(args), project, dict(environment), timeout))
        home = Path(environment["HOME"])
        if len(self.calls) == 1:
            requested_mode = self.mode
            self.mode = "lost-personal" if requested_mode == "first-failure" else "passed"
            result = super().execute(args, project, environment, timeout)
            self.mode = requested_mode
            self.first_files = _tree_bytes(project, home)
            return result
        self.repeated_files = _tree_bytes(project, home)
        _reinstall_fault(project, home, self.mode)
        return InstallerCommandResult(
            args, str(project), "completed", 0, None, b"synthetic repeat\n"
        )


_SKILL_FILE = _SKILL + "/SKILL.md"
_SKILL_SOURCE = b"# Synthetic skill\n"
_SKILL_ALTERED = _SKILL_SOURCE + b"\nSandbox skill repair witness.\n"


class CodeBuddySkillRepairCase(CodeBuddyReinstallCase):
    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, "repair-skill")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if not self.calls:
            return super().execute(args, project, environment, timeout)
        self.calls.append((list(args), project, dict(environment), timeout))
        skill = Path(environment["HOME"]) / _SKILL_FILE
        assert skill.read_bytes() == _SKILL_ALTERED
        if self.mode != "no-op":
            if self.mode != "missing-skill-backup":
                _write(
                    Path(str(skill) + ".bak"),
                    b"Wrong\n" if self.mode == "wrong-skill-backup" else skill.read_bytes(),
                )
            if self.mode != "only-backup":
                skill.write_bytes(_SKILL_SOURCE)
            _reinstall_fault(project, Path(environment["HOME"]), self.mode)
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"repair\n")


class CodeBuddySkillBackupCase(CodeBuddyReinstallCase):
    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, "preserve-skill-backup")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if not self.calls:
            return super().execute(args, project, environment, timeout)
        home = Path(environment["HOME"])
        skill = home / _SKILL_FILE
        backup = Path(str(skill) + ".bak")
        assert skill.read_bytes() == _SKILL_SOURCE
        assert backup.read_bytes() == _SKILL_SOURCE + b"\nSandbox previous backup witness.\n"
        if self.mode == "missing-skill-backup":
            backup.unlink()
        elif self.mode == "wrong-skill-backup":
            backup.write_bytes(_SKILL_SOURCE)
        elif self.mode == "registry":
            _write(project / (_SETTINGS + ".graphify-state.json"), b"{}\n")
        _reinstall_fault(project, home, self.mode)
        self.calls.append((list(args), project, dict(environment), timeout))
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"preserve\n")


class CodeBuddyMarkdownRepairCase(CodeBuddyReinstallCase):
    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, "repair-markdown-section")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if not self.calls:
            return super().execute(args, project, environment, timeout)
        markdown = project / "CODEBUDDY.md"
        assert b"Sandbox altered Markdown section." in markdown.read_bytes()
        if self.mode != "no-op":
            markdown.write_bytes(self.first_files["project/CODEBUDDY.md"])
        if self.mode == "lost-prefix":
            markdown.write_bytes(b"## graphify" + markdown.read_bytes().split(b"## graphify", 1)[1])
        elif self.mode == "lost-suffix":
            markdown.write_bytes(markdown.read_bytes().split(b"## Changes", 1)[0])
        elif self.mode == "foreign":
            (Path(environment["HOME"]) / "personal-notes.txt").write_bytes(b"Lost\n")
        elif self.mode == "registry":
            _write(project / (_SETTINGS + ".graphify-state.json"), b"{}\n")
        _reinstall_fault(project, Path(environment["HOME"]), self.mode)
        self.calls.append((list(args), project, dict(environment), timeout))
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"repair\n")


class CodeBuddyMissingMarkdownRepairCase(CodeBuddyReinstallCase):
    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, "repair-missing-markdown-section")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if not self.calls:
            result = super().execute(args, project, environment, timeout)
            if self.mode in {"first-append", "first-prepend"}:
                markdown = project / "CODEBUDDY.md"
                section = b"## graphify\nUse the synthetic graph.\n"
                personal = markdown.read_bytes().replace(section + b"\n", b"", 1)
                variants = {
                    "first-append": personal + b"\n" + section,
                    "first-prepend": section + b"\n" + personal,
                }
                markdown.write_bytes(variants[self.mode])
            return result
        markdown = project / "CODEBUDDY.md"
        assert b"## graphify" not in markdown.read_bytes()
        section = b"## graphify\nUse the synthetic graph.\n"
        personal = markdown.read_bytes()
        content = self.first_files["project/CODEBUDDY.md"]
        variants = {
            "append": personal + b"\n" + section,
            "prepend": section + b"\n" + personal,
            "no-op": personal,
            "duplicate": content + b"\n" + section,
            "malformed": content.replace(b"## graphify", b"### graphify"),
            "wrong-body": content.replace(b"Use the synthetic graph.", b"Wrong body."),
            "lost-prefix": b"## graphify" + content.split(b"## graphify", 1)[1],
            "lost-suffix": content.split(b"## Changes", 1)[0],
            "reordered": (
                b"## Changes\nExplain proposed changes.\n\n"
                + section
                + b"\n# My project\n\n## Language\nRespond in English.\n"
            ),
        }
        content = variants.get(self.mode, content)
        markdown.write_bytes(content)
        if self.mode == "foreign":
            (Path(environment["HOME"]) / "personal-notes.txt").write_bytes(b"Lost\n")
        elif self.mode == "registry":
            _write(project / (_SETTINGS + ".graphify-state.json"), b"{}\n")
        _reinstall_fault(project, Path(environment["HOME"]), self.mode)
        self.calls.append((list(args), project, dict(environment), timeout))
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"repair\n")


class CodeBuddyMissingHookCase(CodeBuddyReinstallCase):
    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, "repair-missing-json-hook")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if not self.calls:
            return super().execute(args, project, environment, timeout)
        settings = project / _SETTINGS
        data = cast(dict[str, Any], json.loads(settings.read_bytes()))
        search: dict[str, object] = {
            "type": "command",
            "command": "graphify hook-guard search",
            "timeout": 10,
        }
        groups = data["hooks"]["PreToolUse"]
        assert groups[0]["hooks"] == [
            {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
        ]
        if self.mode == "separate-group":
            groups.append({"matcher": "Bash|Grep", "hooks": [search]})
        elif self.mode != "no-op":
            groups[0]["hooks"].append(search)
        _missing_hook_fault(data, self.mode)
        settings.write_text(json.dumps(data, indent=4))
        _reinstall_fault(project, Path(environment["HOME"]), self.mode)
        self.calls.append((list(args), project, dict(environment), timeout))
        return InstallerCommandResult(args, str(project), "completed", 0, None, b"repair\n")


def _missing_hook_fault(data: dict[str, Any], mode: str) -> None:
    groups = data["hooks"]["PreToolUse"]
    if mode == "malformed-group":
        data["hooks"]["PreToolUse"] = [42]
    elif mode == "wrong-hook":
        groups[0]["hooks"][-1]["timeout"] = 99
    elif mode == "read-hook":
        groups[1]["hooks"][0]["timeout"] = 99
    elif mode == "extra-field":
        data["unexpected"] = True
    elif mode == "metadata":
        data["metadata"]["owner"] = "lost"
    elif mode == "group-field":
        groups[0]["unexpected"] = True
    elif mode == "order":
        data["hooks"]["PostToolUse"][0]["hooks"].reverse()


def _append_search(entries: list[object], search: dict[str, object]) -> None:
    if search not in entries:
        entries.append(search)
