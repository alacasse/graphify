"""Host effects remain portable and independent of target names."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
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
    effect_identity,
)
from tools.install_sandbox.host.effect_reader import EffectSpecReader

FIXTURE = Path(__file__).parents[2] / "fixtures" / "codebuddy-effects.yaml"


def context() -> SubjectContext:
    return SubjectContext(
        "controlled-fixture",
        ("controlled", "install"),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
    )


@pytest.mark.parametrize("timeout", [11, True, None])
def test_transported_hook_must_match_subject_timeout_rule(timeout: object) -> None:
    case = build_reinstall_case(EffectSpecReader().read(FIXTURE), context())
    payload = json.loads(case.to_json())
    payload["effects"]["effects"][2]["hooks"][0]["content"]["timeout"] = timeout
    with pytest.raises(ValueError, match="Hook timeout contradicts"):
        EffectInstallCase.from_json(json.dumps(payload))


def test_exact_yaml_and_rename(tmp_path: Path) -> None:
    reader = EffectSpecReader()
    spec = reader.read(FIXTURE)
    skill, markdown, hooks = spec.effects
    assert isinstance(skill, SkillEffect)
    assert skill.destination == Destination("home", ".codebuddy/skills/graphify")
    assert skill.source == "skill.md"
    assert isinstance(markdown, MarkdownSectionEffect)
    assert markdown.destination == Destination("project", "CODEBUDDY.md")
    assert isinstance(hooks, JsonHooksEffect)
    assert hooks.destination == Destination("project", ".codebuddy/settings.json")
    assert [(hook.matcher, hook.content["command"]) for hook in hooks.hooks] == [
        ("Bash|Grep", "graphify hook-guard search"),
        ("Read|Glob", "graphify hook-guard read"),
    ]
    renamed = tmp_path / "independent-name.yaml"
    renamed.write_text(FIXTURE.read_text())
    assert reader.read(renamed) == spec
    assert build_reinstall_case(spec, context(), "renamed").effects == spec


def test_markdown_only_case_and_strict_roundtrip() -> None:
    effect = MarkdownSectionEffect("always_on/claude-md.md", Destination("project", "DOC.md"))
    spec = EffectSpec((effect,))
    case = build_reinstall_case(spec, context())
    assert case.operations == ["install", "install"]
    assert all("settings.json" not in file["path"] for file in case.initial_files)
    assert EffectInstallCase.from_json(case.to_json()) == case
    raw = json.loads(case.to_json())
    raw["operations"] = ["install"]
    with pytest.raises(ValueError, match="operations"):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "path", ["settings.json.graphify-bak", "settings.json.graphify.lock", "settings.json.bak"]
)
def test_auxiliary_collision(path: str) -> None:
    payload = FIXTURE.read_text().replace("path: CODEBUDDY.md", f"path: .codebuddy/{path}")
    with pytest.raises(ValueError, match="overlap"):
        EffectSpecReader().from_yaml(payload)


@pytest.mark.parametrize(
    "fragment", ["kind: shell-script", "kind: markdown-section\n    unknown: true"]
)
def test_unknown_effect_and_fields(fragment: str) -> None:
    payload = FIXTURE.read_text().replace("kind: markdown-section", fragment)
    with pytest.raises(ValueError):
        EffectSpecReader().from_yaml(payload)


def test_missing_rule_and_duplicate_field_rejected() -> None:
    case = build_reinstall_case(EffectSpecReader().read(FIXTURE), context())
    raw = json.loads(case.to_json())
    del raw["subject"]["rules"]["json_backup"]
    with pytest.raises(ValueError, match="Expected fields"):
        EffectInstallCase.from_json(json.dumps(raw))
    with pytest.raises(ValueError, match="Duplicate"):
        EffectSpecReader().from_yaml(FIXTURE.read_text() + "scope: project\n")


def test_unsupported_rule_and_path_rejected() -> None:
    spec = EffectSpecReader().read(FIXTURE)
    subject = SubjectContext(
        "controlled",
        ("install",),
        "METADATA",
        EffectRules(11, "persistent", ".graphify-bak", ".bak", False),
    )
    with pytest.raises(ValueError, match="JSON hooks reinstall rule"):
        build_reinstall_case(spec, subject)
    with pytest.raises(ValueError, match="relative path"):
        Destination("project", "../escape")
    assert effect_identity(spec.effects[1]) == (
        "markdown-section",
        "project",
        "CODEBUDDY.md",
        "## graphify",
    )


def test_personal_witnesses_cannot_collide_with_effects() -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".codebuddy/skills/graphify")
    )
    markdown = MarkdownSectionEffect(
        "always_on/claude-md.md", Destination("home", ".codebuddy/skills/personal-effect-0.txt")
    )
    case = build_reinstall_case(EffectSpec((skill, markdown)), context())
    paths = [(file["root"], file["path"]) for file in case.initial_files]
    assert len(paths) == len(set(paths))
    assert any(path.startswith("sandbox-personal-0-") for _, path in paths)
    assert EffectInstallCase.from_json(case.to_json()) == case


@pytest.mark.parametrize("section_first", [True, False])
@pytest.mark.parametrize(
    "path", [".cache/graphify/skill-locks", ".cache/graphify", ".cache/graphify/skill-locks/file"]
)
def test_skill_lock_directory_cannot_be_a_markdown_file(section_first: bool, path: str) -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".codebuddy/skills/graphify")
    )
    markdown = MarkdownSectionEffect("always_on/claude-md.md", Destination("home", path))
    effects = (markdown, skill) if section_first else (skill, markdown)
    with pytest.raises(ValueError, match="overlap"):
        build_reinstall_case(EffectSpec(effects), context())


@pytest.mark.parametrize("section_first", [True, False])
@pytest.mark.parametrize(
    "destination",
    [
        Destination("home", "instructions.md"),
        Destination("home", ".cache/graphify/skill-locks-other"),
        Destination("project", ".cache/graphify/skill-locks"),
    ],
)
def test_disjoint_skill_and_markdown_destinations_accept_either_order(
    section_first: bool, destination: Destination
) -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".codebuddy/skills/graphify")
    )
    markdown = MarkdownSectionEffect("always_on/claude-md.md", destination)
    effects = (markdown, skill) if section_first else (skill, markdown)
    case = build_reinstall_case(EffectSpec(effects), context())
    assert case.operations == ["install", "install"]
    assert EffectInstallCase.from_json(case.to_json()) == case


@pytest.mark.parametrize("hooks_first", [True, False])
def test_skill_lock_directory_cannot_be_a_json_file(hooks_first: bool) -> None:
    spec = EffectSpecReader().read(FIXTURE)
    skill, _, hooks = spec.effects
    assert isinstance(hooks, JsonHooksEffect)
    collision = JsonHooksEffect(Destination("home", ".cache/graphify/skill-locks"), hooks.hooks)
    effects = (collision, skill) if hooks_first else (skill, collision)
    with pytest.raises(ValueError, match="overlap"):
        build_reinstall_case(EffectSpec(effects), context())


@pytest.mark.parametrize(
    "path", [".cache/graphify/skill-locks", ".cache/graphify", ".cache/graphify/skill-locks/skill"]
)
def test_skill_destination_cannot_overlap_its_own_lock_directory(path: str) -> None:
    skill = SkillEffect("skill.md", "skills/claude/references", Destination("home", path))
    with pytest.raises(ValueError, match="overlap"):
        build_reinstall_case(EffectSpec((skill,)), context())


@pytest.mark.parametrize("home_first", [True, False])
def test_shared_lock_reservations_preserve_multiple_skills_diagnostic(home_first: bool) -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".codebuddy/skills/graphify")
    )
    second = SkillEffect("skill.md", "skills/claude/references", Destination("project", "skill"))
    effects = (skill, second) if home_first else (second, skill)
    spec = EffectSpec(effects)
    with pytest.raises(ValueError, match="Multiple skill effects"):
        build_reinstall_case(spec, context())
