"""Native effect guarantees tested against literal, independently written observations."""

import json
from copy import deepcopy
from pathlib import PurePosixPath

import pytest

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.spec import HookExpectation


def snapshot(files: dict[tuple[str, str], bytes]) -> FilesystemSnapshot:
    result = FilesystemSnapshot(contents=dict(files))
    directories = {(root, ".") for root in ("project", "home", "subject")}
    for root, path in files:
        directories.update((root, str(parent)) for parent in PurePosixPath(path).parents)
        result.entries.append({"root": root, "path": path, "kind": "file"})
    result.entries.extend(
        {"root": root, "path": path, "kind": "directory", "listing_complete": True}
        for root, path in sorted(directories)
    )
    return result


def context() -> SubjectContext:
    return SubjectContext(
        "literal-subject",
        ("python", "-m", "fake"),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
    )


def test_markdown_only_composition_preserves_text_and_reinstall_bytes() -> None:
    case = build_reinstall_case(
        EffectSpec((MarkdownSectionEffect("section.md", Destination("project", "GUIDE.md")),)),
        context(),
    )
    before = snapshot({(f["root"], f["path"]): f["content"].encode() for f in case.initial_files})
    expected = snapshot({("subject", "section.md"): b"## graphify\nRead graph.\n"})
    after = deepcopy(before)
    after.contents[("project", "GUIDE.md")] += b"\n## graphify\nRead graph.\n"
    verifier = EffectVerifier()
    assert verifier.verify_initial(case, expected, before).complete
    assert not verifier.verify(case, expected, before, after).mismatches
    assert not verifier.verify(case, expected, after, after).mismatches
    reformatted = deepcopy(after)
    reformatted.contents[("project", "GUIDE.md")] += b"\n"
    assert any(
        m.type == "unexpected_change"
        for m in verifier.verify(case, expected, after, reformatted).mismatches
    )


@pytest.mark.parametrize("defect", ["duplicate", "wrong", "personal", "missing-source"])
def test_markdown_defects_fail(defect: str) -> None:
    case = build_reinstall_case(
        EffectSpec((MarkdownSectionEffect("section.md", Destination("project", "GUIDE.md")),)),
        context(),
    )
    files = {(f["root"], f["path"]): f["content"].encode() for f in case.initial_files}
    before = snapshot(files)
    expected = snapshot({("subject", "section.md"): b"## graphify\nRead graph.\n"})
    files[("project", "GUIDE.md")] += b"\n## graphify\nRead graph.\n"
    if defect == "duplicate":
        files[("project", "GUIDE.md")] += b"## graphify\nRead graph.\n"
    elif defect == "wrong":
        files[("project", "GUIDE.md")] = files[("project", "GUIDE.md")].replace(
            b"Read graph", b"Bad"
        )
    elif defect == "personal":
        files[("project", "GUIDE.md")] = b"## graphify\nRead graph.\n"
    else:
        expected.contents.clear()
    result = EffectVerifier().verify(case, expected, before, snapshot(files))
    assert result.mismatches or result.obstacles


def test_composed_effects_and_corrupted_skill_reference_backup_or_hook() -> None:
    hook = HookExpectation(
        "search",
        "PreToolUse",
        "Bash|Grep",
        {"type": "command", "command": "graphify search", "timeout": 10},
    )
    spec = EffectSpec(
        (
            SkillEffect("skill.md", "refs", Destination("home", "skills/graphify")),
            JsonHooksEffect(Destination("project", "settings.json"), (hook,)),
        )
    )
    case = build_reinstall_case(spec, context())
    initial = {(f["root"], f["path"]): f["content"].encode() for f in case.initial_files}
    before = snapshot(initial)
    expected = snapshot(
        {
            ("subject", "skill.md"): b"Skill body\n",
            ("subject", "refs/a.md"): b"Reference body\n",
            ("subject", "METADATA"): b"Name: sample\nVersion: 1.2.3\n",
        }
    )
    expected.skill_lock = ".cache/graphify/skill-locks/literal.lock"
    installed = dict(initial)
    settings = json.loads(initial[("project", "settings.json")])
    settings["hooks"]["PreToolUse"].append({"matcher": "Bash|Grep", "hooks": [hook.content]})
    installed.update(
        {
            ("project", "settings.json"): json.dumps(settings).encode(),
            ("project", "settings.json.graphify-bak"): initial[("project", "settings.json")],
            ("home", "skills/graphify/SKILL.md"): b"Skill body\n",
            ("home", "skills/graphify/references/a.md"): b"Reference body\n",
            ("home", "skills/graphify/.graphify_version"): b"1.2.3",
            ("home", expected.skill_lock): b"",
        }
    )
    verifier = EffectVerifier()
    assert not verifier.verify_initial(case, expected, before).mismatches
    result = verifier.verify(case, expected, before, snapshot(installed))
    assert result.complete and not result.mismatches, result
    for key in [
        ("home", "skills/graphify/SKILL.md"),
        ("home", "skills/graphify/references/a.md"),
        ("project", "settings.json.graphify-bak"),
    ]:
        corrupted = {**installed, key: b"wrong"}
        assert verifier.verify(case, expected, before, snapshot(corrupted)).mismatches
    settings["hooks"]["PreToolUse"].append({"matcher": "Bash|Grep", "hooks": [hook.content]})
    installed[("project", "settings.json")] = json.dumps(settings).encode()
    assert any(
        m.type == "hook_count"
        for m in verifier.verify(case, expected, before, snapshot(installed)).mismatches
    )


@pytest.mark.parametrize("defect", ["incomplete", "missing-bytes", "unrelated", "unknown-root"])
def test_incomplete_observations_and_unrelated_changes_cannot_pass(defect: str) -> None:
    case = build_reinstall_case(
        EffectSpec((MarkdownSectionEffect("section.md", Destination("project", "GUIDE.md")),)),
        context(),
    )
    initial = {(f["root"], f["path"]): f["content"].encode() for f in case.initial_files}
    before = snapshot(initial)
    expected = snapshot({("subject", "section.md"): b"## graphify\nRead graph.\n"})
    installed = {
        **initial,
        ("project", "GUIDE.md"): initial[("project", "GUIDE.md")] + b"\n## graphify\nRead graph.\n",
    }
    if defect == "unrelated":
        installed[("home", "unrelated.txt")] = b"unexpected"
    after = snapshot(installed)
    if defect == "incomplete":
        after.entries[-1]["listing_complete"] = False
    elif defect == "missing-bytes":
        after.contents.pop(("project", "GUIDE.md"))
    elif defect == "unknown-root":
        after.entries = [
            entry for entry in after.entries if (entry["root"], entry["path"]) != ("home", ".")
        ]
    result = EffectVerifier().verify(case, expected, before, after)
    assert result.mismatches or result.obstacles


@pytest.mark.parametrize("variation", ["extension", "wrong-timeout", "added-personal-hook"])
def test_hook_extensions_preserve_expected_fields_and_personal_json(variation: str) -> None:
    hook = HookExpectation(
        "search",
        "PreToolUse",
        "Bash|Grep",
        {"type": "command", "command": "graphify search", "timeout": 10},
    )
    case = build_reinstall_case(
        EffectSpec((JsonHooksEffect(Destination("project", "settings.json"), (hook,)),)),
        context(),
    )
    initial = {(f["root"], f["path"]): f["content"].encode() for f in case.initial_files}
    before = snapshot(initial)
    document = json.loads(initial[("project", "settings.json")])
    content = {**hook.content, "additional": "installer metadata"}
    if variation == "wrong-timeout":
        content["timeout"] = 11
    document["hooks"]["PreToolUse"].append({"matcher": "Bash|Grep", "hooks": [content]})
    if variation == "added-personal-hook":
        document["hooks"]["PreToolUse"].append(
            {"matcher": "Read", "hooks": [{"type": "command", "command": "unexpected"}]}
        )
    installed = {
        **initial,
        ("project", "settings.json"): json.dumps(document).encode(),
        ("project", "settings.json.graphify-bak"): initial[("project", "settings.json")],
    }
    result = EffectVerifier().verify(case, snapshot({}), before, snapshot(installed))
    assert result.complete
    if variation == "extension":
        assert not result.mismatches
        stable = EffectVerifier().verify(
            case, snapshot({}), snapshot(installed), snapshot(installed)
        )
        assert stable.complete and not stable.mismatches
    elif variation == "wrong-timeout":
        assert any(m.type == "hook_count" for m in result.mismatches)
    else:
        assert any(m.type == "user_content_lost" for m in result.mismatches)
