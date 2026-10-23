"""Controlled host transport and literal subject independent of expectations."""

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import yaml

from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import EffectRules, SubjectContext
from tools.install_sandbox.host.docker_runtime import ContainerRunResult

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/generic-effects.yaml"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def arrange(root: Path, *, markdown_only: bool = False) -> tuple[Path, Path, Path]:
    subject = root / "subject"
    for name, content in {
        "package.md": "# Synthetic package\n",
        "reference-data/nested/reference.md": "Independent nested reference.\n",
        "instructions.md": "## graphify\nConsult the synthetic map.\n",
        "METADATA": "Metadata-Version: 2.4\nName: synthetic\nVersion: 8.7.6\n",
    }.items():
        write(subject / name, content)
    context = SubjectContext(
        "synthetic-subject",
        ("install",),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
    )
    context_file = root / "context.json"
    context_file.write_text(json.dumps(asdict(context)))
    spec_file = root / "effects.yaml"
    payload = FIXTURE.read_text()
    if markdown_only:
        raw = cast(dict[str, Any], yaml.safe_load(payload))
        raw["effects"] = [
            effect for effect in raw["effects"] if effect["kind"] == "markdown-section"
        ]
        payload = yaml.safe_dump(raw)
    spec_file.write_text(payload)
    return subject, spec_file, context_file


class LiteralInstaller:
    def __init__(self, markdown_only: bool = False) -> None:
        self.markdown_only = markdown_only
        self.calls: list[list[str]] = []

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert timeout == 60
        self.calls.append(args)
        if not self.markdown_only:
            self._skill(Path(environment["HOME"]))
            self._hooks(project)
        path = project / "GUIDE.md"
        content = path.read_text()
        if "Replace this placeholder." in content:
            path.write_text(
                content.replace(
                    "## graphify\nReplace this placeholder.\n\n",
                    "## graphify\nConsult the synthetic map.\n",
                )
            )
        elif "## graphify" not in content:
            separator = "" if "## Personal before" in content else "\n"
            path.write_text(content + separator + "## graphify\nConsult the synthetic map.\n")
        return InstallerCommandResult(args, str(project), "completed", 0, None)

    @staticmethod
    def _skill(home: Path) -> None:
        skill = home / ".synthetic/skills/package"
        write(skill / "SKILL.md", "# Synthetic package\n")
        write(skill / "references/nested/reference.md", "Independent nested reference.\n")
        write(skill / ".graphify_version", "8.7.6")
        digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
        write(home / f".cache/graphify/skill-locks/{digest}.lock", "")

    @staticmethod
    def _hooks(project: Path) -> None:
        path = project / ".synthetic/config.json"
        backup = path.with_name("config.json.graphify-bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        data = cast(dict[str, Any], json.loads(path.read_text()))
        groups = data["hooks"]["PreToolUse"]
        search = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
        read = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}
        if search not in groups[0]["hooks"]:
            groups[0]["hooks"].append(search)
            groups.append({"matcher": "Read|Glob", "hooks": [read]})
        path.write_text(json.dumps(data) + "\n")


def completed() -> ContainerRunResult:
    return ContainerRunResult(
        "controlled", "completed", "complete", 0, None, True, "", "", "Controlled transport"
    )


class ControlledTransport:
    """Test injection at the existing container harness seam; execute the real engine."""

    def __init__(self, root: Path, *, markdown_only: bool = False) -> None:
        self.root = root
        self.installer = LiteralInstaller(markdown_only)
        self.interrupted = False
        self.subject = root / "prepared"
        self.executable = root / "simulated-executable"
        self.executable.write_text("Controlled installer identity.\n")

    def __enter__(self) -> "ControlledTransport":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def prepare(self, subject: Path, output: Path) -> ContainerRunResult:
        shutil.copytree(subject, self.subject)
        output.mkdir(parents=True)
        return completed()

    def run_case(self, *, case_file: Path, output_directory: Path) -> ContainerRunResult:
        InstallTestRunner(InstallerDriver(self.installer.execute)).run_case(
            reference_sources=self.subject,
            prepared_executable=self.executable,
            case_file=case_file,
            work_directory=self.root / "environment" / case_file.stem,
            output_directory=output_directory,
        )
        return completed()

    def cleanup(self) -> ContainerRunResult:
        shutil.rmtree(self.subject, ignore_errors=True)
        shutil.rmtree(self.root / "environment", ignore_errors=True)
        self.executable.unlink(missing_ok=True)
        return completed()
