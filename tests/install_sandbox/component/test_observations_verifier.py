"""Local first-install proofs from literal effects, independent of the installer."""

import json
import posixpath
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.environment import TestEnvironment as Environment
from tools.install_sandbox.results import FilesystemSnapshot, VerificationResult
from tools.install_sandbox.results import TestResultWriter as ResultWriter
from tools.install_sandbox.verifier import InstallVerifier

_CASE = Path(__file__).with_name("fixtures") / "first-install.json"
_SKILL = b"# Local skill\nRead references/one.md.\n"
_MARKDOWN = b"## graphify\nUse the graph.\n\nKeep this internal blank line.\n"
_REFERENCES = {"one.md": b"First reference.\n", "nested/two.md": b"Second reference.\n"}


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
        put(skill, _SKILL)
        put(skill.parent / ".graphify_version", b"Arbitrary version, presence only\n")
        for name, content in _REFERENCES.items():
            put(skill.parent / "references" / name, content)
        markdown = self.path("markdown")
        put(markdown, markdown.read_bytes() + b"\n" + _MARKDOWN)
        config = self.path("json")
        data = json.loads(config.read_bytes())
        data[self.case.spec.json_list].append(posixpath.relpath(skill, config.parent))
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
    put(subject / case.spec.skill_source, _SKILL)
    put(subject / case.spec.markdown_source, _MARKDOWN)
    for name, content in _REFERENCES.items():
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


@pytest.mark.parametrize("renamed", [False, True])
def test_conforming_effects_and_independent_expected_sources(tmp_path: Path, renamed: bool) -> None:
    run = scenario(tmp_path, renamed=renamed)
    run.effects()
    shutil.rmtree(run.subject)
    assert_passed(run.verify())


@pytest.mark.parametrize("defect", ["missing", "changed", "extra"])
def test_reference_inventory_and_bytes(tmp_path: Path, defect: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    reference = run.path("skill").parent / "references/nested/two.md"
    if defect == "missing":
        reference.unlink()
    elif defect == "changed":
        put(reference, b"Altered reference.\n")
    else:
        reference = reference.parent / "extra.md"
        put(reference, b"Unexpected reference.\n")
    assert_mismatch(run.verify(), reference, run.environment.project)


@pytest.mark.parametrize("artifact", ["skill", "version"])
def test_required_skill_bytes_and_version_presence(tmp_path: Path, artifact: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    path = run.path("skill")
    if artifact == "skill":
        put(path, _SKILL.replace(b"\n", b"\r\n"))
    else:
        path = path.parent / ".graphify_version"
        path.unlink()
    assert_mismatch(run.verify(), path, run.environment.project)


@pytest.mark.parametrize("separator", [b"", b"\n", b"\n\n\n"])
def test_only_graphify_boundary_blank_lines_are_tolerated(tmp_path: Path, separator: bytes) -> None:
    run = scenario(tmp_path)
    run.effects()
    initial = run.before.contents[
        ("project", str(run.path("markdown").relative_to(run.environment.project)))
    ]
    put(run.path("markdown"), initial + separator + _MARKDOWN + separator)
    assert_passed(run.verify())


@pytest.mark.parametrize("defect", ["space", "blank", "order", "graphify", "duplicate"])
def test_markdown_preserves_exact_text_and_section_order(tmp_path: Path, defect: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    path = run.path("markdown")
    content = path.read_bytes()
    changes = {
        "space": content.replace(b"Respond in English.", b"Respond in English. "),
        "blank": content.replace(b"## Language\n", b"## Language\n\n"),
        "order": content.replace(b"## Language", b"## Temporary")
        .replace(b"## Changes", b"## Language")
        .replace(b"## Temporary", b"## Changes"),
        "graphify": content.replace(b"graph.\n\nKeep", b"graph.\nKeep"),
        "duplicate": content + b"\n" + _MARKDOWN,
    }
    put(path, changes[defect])
    assert_mismatch(run.verify(), path, run.environment.project)


@pytest.mark.parametrize("defect", ["value", "removed", "duplicate", "user_order", "type"])
def test_json_values_and_user_list_order(tmp_path: Path, defect: str) -> None:
    run = scenario(tmp_path)
    path = run.path("json")
    put(path, b'{"theme":"dark","instructions":["my-instructions.md","second.md"]}')
    run.before = run.environment.observe(run.writer, "before")
    run.effects()
    data = json.loads(path.read_bytes())
    if defect == "value":
        data["theme"] = "light"
    elif defect == "removed":
        del data["theme"]
    elif defect == "duplicate":
        data["instructions"].append(data["instructions"][-1])
    elif defect == "user_order":
        data["instructions"][:2] = ["second.md", "my-instructions.md"]
    else:
        data["theme"] = False
    put(path, json.dumps(data).encode())
    assert_mismatch(run.verify(), path, run.environment.project)


@pytest.mark.parametrize("location", ["home", "project", "target", "witness"])
@pytest.mark.parametrize("change", ["add", "remove", "change"])
def test_preservation_outside_specific_destinations(
    tmp_path: Path,
    location: str,
    change: str,
) -> None:
    run = scenario(tmp_path, renamed=True)
    root = run.environment.home if location == "home" else run.environment.project
    paths = {
        "home": root / "personal-notes.txt",
        "project": root / "neighbor.txt",
        "target": root / run.case.spec.directory / "neighbor.txt",
        "witness": run.path("json").parent / "my-instructions.md",
    }
    path = paths[location]
    if change == "add":
        path = path.with_name("unexpected.txt")
    elif not path.exists():
        put(path, b"Preserve this neighbor.\n")
    run.before = run.environment.observe(run.writer, "before")
    run.effects()
    if change == "remove":
        path.unlink()
    else:
        put(path, b"Unexpected content.\n")
    result = run.verify()
    assert_mismatch(result, path, root)
    assert any(
        item.root == ("home" if location == "home" else "project") for item in result.mismatches
    )


@pytest.mark.parametrize("phase", ["expected", "before", "after"])
@pytest.mark.parametrize("operation", ["read_bytes", "iterdir"])
def test_observation_failure_is_an_obstacle_not_a_proven_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    operation: str,
) -> None:
    run = scenario(tmp_path)
    target = run.path("markdown") if operation == "read_bytes" else run.environment.home
    if phase == "expected":
        source = (
            run.case.spec.skill_source
            if operation == "read_bytes"
            else (run.case.spec.references_source)
        )
        target = run.subject / source
    original = getattr(Path, operation)

    def fail_selected(path: Path):
        if path == target:
            raise PermissionError("Controlled observation failure")
        return original(path)

    run.effects()
    after: FilesystemSnapshot | None = None
    with monkeypatch.context() as patch:
        patch.setattr(Path, operation, fail_selected)
        if phase == "expected":
            run.expected = run.environment.preserve_expected(run.subject, run.writer)
        elif phase == "before":
            run.before = run.environment.observe(run.writer, "before")
        else:
            after = run.environment.observe(run.writer, "after")
    if after is None:
        after = run.environment.observe(run.writer, "after")
    result = InstallVerifier().verify(run.case, run.expected, run.before, after)
    assert not result.complete
    assert any("Controlled observation failure" in item["reason"] for item in result.obstacles)
    assert not any(item.type == "missing_file" for item in result.mismatches)


def test_unknown_reference_subtree_does_not_report_missing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = scenario(tmp_path)
    run.effects()
    directory = run.path("skill").parent / "references"
    original = Path.iterdir

    def fail_reference_listing(path: Path):
        if path == directory:
            raise PermissionError("Cannot enumerate references")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", fail_reference_listing)
    result = run.verify()
    assert not result.complete
    assert result.obstacles
    assert not any(item.type == "missing_file" for item in result.mismatches)


def test_evidence_is_consultable_after_all_observed_roots_are_deleted(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    run.effects()
    reference = run.path("skill").parent / "references/one.md"
    put(reference, b"Wrong reference retained for diagnosis.\n")
    result = run.verify()
    assert_mismatch(result, reference, run.environment.project)
    for root in (run.subject, run.environment.project, run.environment.home):
        shutil.rmtree(root)
    output = run.writer.output_directory
    verification = json.loads((output / "steps/0/verification.json").read_bytes())
    assert verification["complete"]
    assert verification["mismatches"]
    preserved: list[bytes] = []
    for name in ("expected.json", "steps/0/before.json", "steps/0/after.json"):
        snapshot = json.loads((output / name).read_bytes())
        for entry in snapshot["entries"]:
            if entry.get("content_file"):
                preserved.append((output / entry["content_file"]).read_bytes())
    assert _SKILL in preserved
    assert _REFERENCES["one.md"] in preserved
    assert b"Wrong reference retained for diagnosis.\n" in preserved
    assert b"Personal document to preserve.\n" in preserved


def test_json_reformatting_preserves_multiple_user_entries(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    path = run.path("json")
    put(path, b'{"theme":"dark","instructions":["first.md","second.md"],"nested":{"n":1}}')
    run.before = run.environment.observe(run.writer, "before")
    run.effects()
    assert_passed(run.verify())


def test_missing_reference_is_proven_by_complete_parent_listing(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    run.effects()
    reference = run.path("skill").parent / "references/one.md"
    reference.unlink()
    result = run.verify()
    assert result.complete
    assert any(
        item.type == "missing_file" and item.path.endswith("/references/one.md")
        for item in result.mismatches
    )


def test_known_mismatch_survives_an_unrelated_observation_obstacle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = scenario(tmp_path)
    run.effects()
    put(run.path("skill"), b"Wrong skill.\n")
    blocked = run.environment.home / "personal-notes.txt"
    original = Path.read_bytes

    def fail_notes(path: Path) -> bytes:
        if path == blocked:
            raise PermissionError("Notes cannot be read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_notes)
    result = run.verify()
    assert not result.complete
    assert any(item.path.endswith("/SKILL.md") for item in result.mismatches)
    assert any(item["path"] == "personal-notes.txt" for item in result.obstacles)


def test_markdown_section_between_user_sections_preserves_both_sides(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    run.effects()
    path = run.path("markdown")
    initial = run.before.contents[("project", str(path.relative_to(run.environment.project)))]
    put(path, initial.replace(b"\n## Changes\n", b"\n\n" + _MARKDOWN + b"\n\n## Changes\n"))
    assert_passed(run.verify())
    put(path, path.read_bytes().replace(b"Explain proposed changes.", b"Changed user section."))
    assert_mismatch(run.verify(), path, run.environment.project)


def test_failed_stat_cannot_prove_missing_file_or_wrong_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = scenario(tmp_path)
    run.effects()
    skill = run.path("skill")
    original = Path.lstat

    def fail_skill_stat(path: Path):
        if path == skill:
            raise PermissionError("Skill metadata cannot be read")
        return original(path)

    monkeypatch.setattr(Path, "lstat", fail_skill_stat)
    result = run.verify()
    relative = str(skill.relative_to(run.environment.project))
    assert not result.complete
    assert any(
        item["operation"] == "stat" and item["path"] == relative for item in result.obstacles
    )
    assert not any(
        item.path == relative and item.type in {"missing_file", "entry_kind"}
        for item in result.mismatches
    )


@pytest.mark.parametrize("defect", [None, "witness", "source", "observation"])
def test_initial_readiness_is_separate_from_installation_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str | None
) -> None:
    run = scenario(tmp_path)
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if defect == "observation" and path == run.environment.home / "personal-notes.txt":
            raise PermissionError("Initial witness cannot be read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    if defect == "witness":
        put(run.environment.home / "personal-notes.txt", b"Wrong initial witness\n")
    if defect == "source":
        (run.subject / run.case.spec.skill_source).unlink()
    expected = run.environment.preserve_expected(run.subject, run.writer)
    before = run.environment.observe(run.writer, "before")
    result = InstallVerifier().verify_initial(run.case, expected, before)
    assert result.complete is (defect is None)
    assert bool(result.obstacles) is (defect is not None)
    assert result.mismatches == []


def test_regular_file_blocking_required_directory_is_not_unknown(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    run.effects()
    parent = run.path("skill").parent
    shutil.rmtree(parent)
    put(parent, b"A regular file cannot contain installation files.\n")
    result = run.verify()
    assert result.complete
    assert any(
        item.type == "missing_file" and item.path.endswith("SKILL.md") for item in result.mismatches
    )


def test_incomplete_source_inventory_does_not_invent_unauthorized_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = scenario(tmp_path)
    references = run.subject / run.case.spec.references_source
    original = Path.iterdir

    def list_directory(path: Path):
        if path == references:
            raise PermissionError("Source references cannot be listed")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", list_directory)
    run.expected = run.environment.preserve_expected(run.subject, run.writer)
    run.effects()
    put(run.environment.project / "unexpected.txt", b"Still an established extra file.\n")
    result = run.verify()
    assert not result.complete
    assert any(item["path"] == run.case.spec.references_source for item in result.obstacles)
    assert all("/references/" not in item.path for item in result.mismatches)
    assert any(item.path == "unexpected.txt" for item in result.mismatches)


def test_removal_of_reference_entry_known_outside_source_inventory_is_reported(
    tmp_path: Path,
) -> None:
    run = scenario(tmp_path)
    extra = run.path("skill").parent / "references/user-note.md"
    put(extra, b"Initial file outside the declared source inventory.\n")
    run.before = run.environment.observe(run.writer, "before")
    run.effects()
    extra.unlink()
    result = run.verify()
    assert_mismatch(result, extra, run.environment.project)
