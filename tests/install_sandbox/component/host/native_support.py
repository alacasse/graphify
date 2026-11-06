"""Controlled host transport and literal subject independent of expectations."""

import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import EffectRules, SubjectContext
from tools.install_sandbox.host.docker_runtime import ContainerRunResult

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/generic-effects.yaml"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def arrange(
    root: Path,
    *,
    markdown_only: bool = False,
    skill: bool = True,
    markdown: bool = True,
    hooks: bool = True,
    skill_root: Literal["home", "project"] = "home",
) -> tuple[Path, Path, Path]:
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
    raw = cast(dict[str, Any], yaml.safe_load(payload))
    enabled = {
        "skill": skill and not markdown_only,
        "markdown-section": markdown,
        "json-hooks": hooks and not markdown_only,
    }
    raw["effects"] = [effect for effect in raw["effects"] if enabled[effect["kind"]]]
    for effect in raw["effects"]:
        if effect["kind"] == "skill":
            effect["destination"]["root"] = skill_root
    payload = yaml.safe_dump(raw)
    spec_file.write_text(payload)
    return subject, spec_file, context_file


def _same_timed_command(candidate: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    # JSON distinguishes the integer timeout from a numerically equal float.
    return type(candidate.get("timeout")) is int and candidate == expected


class LiteralInstaller:
    def __init__(
        self,
        markdown_only: bool = False,
        *,
        skill: bool = True,
        markdown: bool = True,
        hooks: bool = True,
        skill_root: Literal["home", "project"] = "home",
    ) -> None:
        self.skill = skill and not markdown_only
        self.markdown = markdown
        self.hooks = hooks and not markdown_only
        self.skill_root = skill_root
        self.calls: list[list[str]] = []
        self.rebuild_references = True
        self.cleanup_references_tmp = True
        self.packaged_stale_reference = False
        self.repair_hook_timeout = True
        self.duplicate_hook_survivor: Literal["first", "last", "all"] = "first"

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert timeout == 60
        self.calls.append(args)
        home = Path(environment["HOME"])
        if self.skill:
            self._skill(home if self.skill_root == "home" else project, home)
        if self.hooks:
            self._hooks(project)
        if self.markdown:
            self._markdown(project)
        return InstallerCommandResult(args, str(project), "completed", 0, None)

    @staticmethod
    def _markdown(project: Path) -> None:
        path = project / "GUIDE.md"
        content = path.read_text()
        if "Replace this placeholder." in content:
            path.write_text(
                content.replace(
                    "## graphify\nReplace this placeholder.\n\n",
                    "## graphify\nConsult the synthetic map.\n",
                )
            )
        elif "\nSandbox altered Markdown section.\n\n" in content:
            path.write_text(
                content.replace(
                    "## graphify\n\nSandbox altered Markdown section.\n\n",
                    "## graphify\nConsult the synthetic map.\n",
                )
            )
        elif "## graphify" not in content:
            separator = "" if "## Personal before" in content else "\n"
            path.write_text(content + separator + "## graphify\nConsult the synthetic map.\n")

    def _skill(self, root: Path, home: Path) -> None:
        skill = root / ".synthetic/skills/package"
        document = skill / "SKILL.md"
        canonical = b"# Synthetic package\n"
        if document.exists() and document.read_bytes() != canonical:
            document.with_name("SKILL.md.bak").write_bytes(document.read_bytes())
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(canonical)
        temporary_references = skill / "references.tmp"
        if (
            self.cleanup_references_tmp
            and temporary_references.is_dir()
            and not temporary_references.is_symlink()
        ):
            shutil.rmtree(temporary_references)
        references = skill / "references"
        if self.rebuild_references and references.exists():
            shutil.rmtree(references)
        write(references / "nested/reference.md", "Independent nested reference.\n")
        if self.packaged_stale_reference:
            write(references / "stale.md", "Packaged stale reference.\n")
        write(skill / ".graphify_version", "8.7.6")
        digest = hashlib.sha256(str(skill.resolve()).encode()).hexdigest()[:16]
        write(home / f".cache/graphify/skill-locks/{digest}.lock", "")

    def _hooks(self, project: Path) -> None:
        path = project / ".synthetic/config.json"
        backup = path.with_name("config.json.graphify-bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        data = cast(dict[str, Any], json.loads(path.read_text()))
        groups = data["hooks"]["PreToolUse"]
        search = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
        read = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}
        # Search and read may live in separate groups; repair each independently.
        for matcher, hook in (("Bash|Grep", search), ("Read|Glob", read)):
            matching = [group for group in groups if group.get("matcher") == matcher]
            if self._existing_hooks(matching, hook, search):
                continue
            # The simulator repairs only its literal timeout variant; personal hooks survive.
            if self.repair_hook_timeout:
                altered = {**hook, "timeout": 11}
                for group in matching:
                    group["hooks"] = [
                        existing
                        for existing in group["hooks"]
                        if not _same_timed_command(existing, altered)
                    ]
            if matching:
                matching[0]["hooks"].append(hook)
            else:
                groups.append({"matcher": matcher, "hooks": [hook]})
        path.write_text(json.dumps(data) + "\n")

    def _existing_hooks(
        self, groups: list[dict[str, Any]], hook: Mapping[str, object], search: Mapping[str, object]
    ) -> bool:
        occurrences = [
            (group, index)
            for group in groups
            for index, item in enumerate(group["hooks"])
            if _same_timed_command(item, hook)
        ]
        if not occurrences:
            return False
        if hook is search and self.duplicate_hook_survivor != "all":
            survivor = occurrences[-1 if self.duplicate_hook_survivor == "last" else 0]
            for group in groups:
                group["hooks"] = [
                    item
                    for index, item in enumerate(group["hooks"])
                    if not _same_timed_command(item, hook)
                    or (group is survivor[0] and index == survivor[1])
                ]
        return True


def completed() -> ContainerRunResult:
    return ContainerRunResult(
        "controlled", "completed", "complete", 0, None, True, "", "", "Controlled transport"
    )


class ControlledTransport:
    """Test injection at the existing container harness seam; execute the real engine."""

    def __init__(
        self,
        root: Path,
        *,
        markdown_only: bool = False,
        skill: bool = True,
        markdown: bool = True,
        hooks: bool = True,
        skill_root: Literal["home", "project"] = "home",
    ) -> None:
        self.root = root
        self.installer = LiteralInstaller(
            markdown_only, skill=skill, markdown=markdown, hooks=hooks, skill_root=skill_root
        )
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
