"""Controlled arrangements shared by sandbox behavior tests."""

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter
from tools.install_sandbox.container.verifier import InstallVerifier
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.results import VerificationResult

_CASE = Path(__file__).resolve().parents[1] / "fixtures" / "first-install.json"


SKILL = b"# Local skill\nRead references/one.md.\n"


MARKDOWN = b"## graphify\nUse the graph.\n\nKeep this internal blank line.\n"


REFERENCES = {"one.md": b"First reference.\n", "nested/two.md": b"Second reference.\n"}


def put(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@dataclass
class Scenario:
    case: InstallTestCase
    environment: Environment
    writer: ResultWriter
    subject: Path
    expected: FilesystemSnapshot
    before: FilesystemSnapshot

    def path(self, key: str) -> Path:
        spec = self.case.spec
        relative = {
            "skill": spec.skill_file,
            "markdown": spec.markdown_file,
            "json": spec.json_file,
        }[key]
        return self.environment.project / spec.directory / relative

    def effects(self) -> None:
        skill = self.path("skill")
        put(skill, SKILL)
        put(skill.parent / ".graphify_version", b"Arbitrary version, presence only\n")
        for name, content in REFERENCES.items():
            put(skill.parent / "references" / name, content)
        markdown = self.path("markdown")
        put(markdown, markdown.read_bytes() + b"\n" + MARKDOWN)
        config = self.path("json")
        data = json.loads(config.read_bytes())
        data[self.case.spec.json_list].append(posixpath.relpath(skill, config.parent))
        data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
            {
                "matcher": "Bash|Grep",
                "hooks": [{"type": "command", "command": "graphify hook-guard search"}],
            }
        )
        put(config, json.dumps(data, indent=4).encode())

    def verify(self) -> VerificationResult:
        after = self.environment.observe(self.writer, "after")
        result = InstallVerifier().verify(self.case, self.expected, self.before, after)
        self.writer.write_verification(result)
        return result


def scenario(tmp_path: Path, *, renamed: bool = False) -> Scenario:
    payload = _CASE.read_text(encoding="utf-8")
    if renamed:
        payload = (
            payload.replace("sandbox-reference", "another-target")
            .replace("skills/graphify/SKILL.md", "packages/custom/ENTRY.md")
            .replace("instructions.md", "notes.md")
            .replace("my-notes.md", "my-instructions.md")
            .replace("settings.json", "preferences.json")
        )
    case = InstallTestCase.from_json(payload)
    environment = Environment(case, tmp_path / "isolated")
    environment.prepare()
    writer = ResultWriter(tmp_path / "results")
    subject = tmp_path / "subject"
    put(subject / case.spec.skill_source, SKILL)
    put(subject / case.spec.markdown_source, MARKDOWN)
    for name, content in REFERENCES.items():
        put(subject / case.spec.references_source / name, content)
    expected = environment.preserve_expected(subject, writer)
    before = environment.observe(writer, "before")
    return Scenario(case, environment, writer, subject, expected, before)


def assert_passed(result: VerificationResult) -> None:
    assert result.complete
    assert result.mismatches == []
    assert result.obstacles == []


def assert_mismatch(result: VerificationResult, path: Path, root: Path) -> None:
    assert result.complete
    assert not result.obstacles
    assert any(item.path == str(path.relative_to(root)) for item in result.mismatches)
