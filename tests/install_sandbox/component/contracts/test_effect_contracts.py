"""Host effects remain portable and independent of target names."""

import json
from pathlib import Path
from typing import Literal

import pytest

from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.host.effect_reader import EffectSpecReader

FIXTURE = Path(__file__).parents[2] / "fixtures" / "generic-effects.yaml"


def structured_spec() -> EffectSpec:
    return EffectSpec(
        (
            SkillEffect(
                "package.md", "reference-data", Destination("home", ".synthetic/skills/package")
            ),
            MarkdownSectionEffect("instructions.md", Destination("project", "GUIDE.md")),
            JsonHooksEffect(
                Destination("project", ".synthetic/config.json"),
                (
                    HookExpectation(
                        "PreToolUse-search",
                        "PreToolUse",
                        "Bash|Grep",
                        {"type": "command", "command": "graphify hook-guard search", "timeout": 10},
                    ),
                    HookExpectation(
                        "PreToolUse-read",
                        "PreToolUse",
                        "Read|Glob",
                        {"type": "command", "command": "graphify hook-guard read", "timeout": 10},
                    ),
                ),
            ),
        )
    )


def context() -> SubjectContext:
    return SubjectContext(
        "controlled-fixture",
        ("controlled", "install"),
        "METADATA",
        EffectRules("persistent", ".graphify-bak", ".bak", False),
    )


def reinstall_case(spec: EffectSpec, subject: SubjectContext) -> EffectInstallCase:
    return next(
        case for case in build_effect_cases(spec, subject).cases if case.name == "reinstall"
    )


@pytest.mark.parametrize("timeout", [11.5, True, None])
def test_transported_hook_timeout_must_be_an_integer(timeout: object) -> None:
    case = reinstall_case(structured_spec(), context())
    payload = json.loads(case.to_json())
    payload["effects"]["effects"][2]["hooks"][0]["content"]["timeout"] = timeout
    with pytest.raises(ValueError, match="Hook timeout must be"):
        EffectInstallCase.from_json(json.dumps(payload))


def test_exact_yaml_and_rename(tmp_path: Path) -> None:
    reader = EffectSpecReader()
    spec = reader.read(FIXTURE).scopes[0].effects
    assert spec is not None
    skill, markdown, hooks = spec.effects
    assert isinstance(skill, SkillEffect)
    assert skill.destination == Destination("home", ".synthetic/skills/package")
    assert skill.source == "package.md"
    assert spec == structured_spec()
    assert isinstance(markdown, MarkdownSectionEffect)
    assert markdown.destination == Destination("project", "GUIDE.md")
    assert isinstance(hooks, JsonHooksEffect)
    assert hooks.destination == Destination("project", ".synthetic/config.json")
    assert [(hook.matcher, hook.content["command"]) for hook in hooks.hooks] == [
        ("Bash|Grep", "graphify hook-guard search"),
        ("Read|Glob", "graphify hook-guard read"),
    ]
    renamed = tmp_path / "independent-name.yaml"
    renamed.write_text(FIXTURE.read_text())
    assert reader.read(renamed).scopes[0].effects == spec


def test_markdown_only_case_and_strict_roundtrip() -> None:
    effect = MarkdownSectionEffect("always_on/claude-md.md", Destination("project", "DOC.md"))
    spec = EffectSpec((effect,))
    case = reinstall_case(spec, context())
    assert case.operations == ["install", "install"]
    assert all("config.json" not in file["path"] for file in case.initial_files)
    assert EffectInstallCase.from_json(case.to_json()) == case
    raw = json.loads(case.to_json())
    raw["operations"] = ["install"]
    with pytest.raises(ValueError, match="operations"):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "path", ["config.json.graphify-bak", "config.json.graphify.lock", "config.json.bak"]
)
def test_auxiliary_collision(path: str) -> None:
    payload = FIXTURE.read_text().replace("path: GUIDE.md", f"path: .synthetic/{path}")
    with pytest.raises(ValueError, match="overlap"):
        EffectSpecReader().from_yaml(payload)


@pytest.mark.parametrize(
    "fragment", ["family: shell-script", "family: markdown-section\n    unknown: true"]
)
def test_unknown_effect_and_fields(fragment: str) -> None:
    payload = FIXTURE.read_text().replace("family: markdown-section", fragment)
    with pytest.raises(ValueError):
        EffectSpecReader().from_yaml(payload)


def test_missing_rule_and_duplicate_field_rejected() -> None:
    case = reinstall_case(structured_spec(), context())
    raw = json.loads(case.to_json())
    del raw["subject"]["rules"]["json_backup"]
    with pytest.raises(ValueError, match="Expected fields"):
        EffectInstallCase.from_json(json.dumps(raw))
    with pytest.raises(ValueError, match="Duplicate"):
        EffectSpecReader().from_yaml(FIXTURE.read_text() + "tool: duplicate\n")


def test_unsupported_rule_and_path_rejected() -> None:
    spec = structured_spec()
    subject = SubjectContext(
        "controlled",
        ("install",),
        "METADATA",
        EffectRules("persistent", ".unsupported", ".bak", False),
    )
    with pytest.raises(ValueError, match="JSON hooks reinstall rule"):
        build_effect_cases(spec, subject)
    with pytest.raises(ValueError, match="relative path"):
        Destination("project", "../escape")


def test_personal_witnesses_cannot_collide_with_effects() -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".synthetic/skills/package")
    )
    markdown = MarkdownSectionEffect(
        "always_on/claude-md.md", Destination("home", ".synthetic/skills/personal-effect-0.txt")
    )
    case = reinstall_case(EffectSpec((skill, markdown)), context())
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
        "skill.md", "skills/claude/references", Destination("home", ".synthetic/skills/package")
    )
    markdown = MarkdownSectionEffect("always_on/claude-md.md", Destination("home", path))
    effects = (markdown, skill) if section_first else (skill, markdown)
    with pytest.raises(ValueError, match="overlap"):
        build_effect_cases(EffectSpec(effects), context())


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
        "skill.md", "skills/claude/references", Destination("home", ".synthetic/skills/package")
    )
    markdown = MarkdownSectionEffect("always_on/claude-md.md", destination)
    effects = (markdown, skill) if section_first else (skill, markdown)
    case = reinstall_case(EffectSpec(effects), context())
    assert case.operations == ["install", "install"]
    assert EffectInstallCase.from_json(case.to_json()) == case


@pytest.mark.parametrize("hooks_first", [True, False])
def test_skill_lock_directory_cannot_be_a_json_file(hooks_first: bool) -> None:
    spec = structured_spec()
    skill, _, hooks = spec.effects
    assert isinstance(hooks, JsonHooksEffect)
    collision = JsonHooksEffect(Destination("home", ".cache/graphify/skill-locks"), hooks.hooks)
    effects = (collision, skill) if hooks_first else (skill, collision)
    with pytest.raises(ValueError, match="overlap"):
        build_effect_cases(EffectSpec(effects), context())


@pytest.mark.parametrize(
    "path", [".cache/graphify/skill-locks", ".cache/graphify", ".cache/graphify/skill-locks/skill"]
)
def test_skill_destination_cannot_overlap_its_own_lock_directory(path: str) -> None:
    skill = SkillEffect("skill.md", "skills/claude/references", Destination("home", path))
    with pytest.raises(ValueError, match="overlap"):
        build_effect_cases(EffectSpec((skill,)), context())


@pytest.mark.parametrize("home_first", [True, False])
def test_shared_lock_reservations_preserve_multiple_skills_diagnostic(home_first: bool) -> None:
    skill = SkillEffect(
        "skill.md", "skills/claude/references", Destination("home", ".synthetic/skills/package")
    )
    second = SkillEffect(
        "skill.md", "skills/claude/references", Destination("project", "skill"), effect_id="second"
    )
    effects = (skill, second) if home_first else (second, skill)
    spec = EffectSpec(effects)
    built = build_effect_cases(spec, context())
    assert not built.cases
    assert all(
        decision.reason == "Multiple skill effects require unavailable lock observation capability"
        for decision in built.decisions
        if decision.classification == "unconstructible"
    )
    reinstall = next(decision for decision in built.decisions if decision.name == "reinstall")
    assert reinstall.classification == "unconstructible"
    assert (
        reinstall.reason == "Multiple skill effects require unavailable lock observation capability"
    )


def test_catalogue_has_strict_independent_preparations() -> None:
    cases = build_effect_cases(structured_spec(), context()).cases
    assert [case.name for case in cases] == [
        "reinstall",
        "missing-section",
        "altered-section",
        "missing-reference",
        "altered-reference",
        "altered-skill",
        "preserve-skill-backup",
        "stale-version",
        "stale-reference",
        "missing-json-hook",
        "missing-json-hook",
    ]
    for case in cases:
        assert EffectInstallCase.from_json(case.to_json()) == case
    raw = json.loads(next(case for case in cases if case.name == "altered-section").to_json())
    assert raw["format"] == "explicit-expectations-v12"
    assert (
        raw["intermediate_preparation"]["body"]
        == "ClNhbmRib3ggYWx0ZXJlZCBNYXJrZG93biBzZWN0aW9uLgoK"
    )
    raw["intermediate_preparation"]["body"] = "Y2hhbmdlZA=="
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize(
    "version",
    [
        "explicit-expectations-v2",
        "explicit-expectations-v3",
        "explicit-expectations-v4",
        "explicit-expectations-v5",
        "explicit-expectations-v6",
        "explicit-expectations-v7",
        "explicit-expectations-v8",
        "explicit-expectations-v9",
        "explicit-expectations-v10",
        "explicit-expectations-v11",
    ],
)
def test_old_case_formats_are_rejected(version: str) -> None:
    raw = json.loads(reinstall_case(structured_spec(), context()).to_json())
    raw["format"] = version
    with pytest.raises(ValueError, match="Unsupported effects case format"):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize("change", ["legacy", "missing", "unknown", "bad-base64"])
def test_prepared_replacement_transport_is_strict(change: str) -> None:
    operation = BoundMarkdownMutation(
        "a" * 64,
        "steps/0/after.json",
        Destination("project", "GUIDE.md"),
        "b" * 64,
        12,
        23,
        b"replacement",
    )
    raw = operation.to_data()
    assert BoundMarkdownMutation.from_data(raw) == operation
    if change == "legacy":
        raw["format"] = "prepared-byte-range-v1"
    elif change == "missing":
        del raw["replacement"]
    elif change == "unknown":
        raw["extra"] = True
    else:
        raw["replacement"] = "!"
    with pytest.raises(ValueError):
        BoundMarkdownMutation.from_data(raw)


def test_multiple_markdown_effects_retain_both_nonconstruction_reasons() -> None:
    spec = EffectSpec(
        (
            MarkdownSectionEffect("first.md", Destination("project", "FIRST.md")),
            MarkdownSectionEffect(
                "second.md", Destination("project", "SECOND.md"), effect_id="second"
            ),
        )
    )
    built = build_effect_cases(spec, context())
    assert [case.name for case in built.cases] == ["reinstall"]
    assert [(item.name, item.classification, item.reason) for item in built.decisions] == [
        (name, "unconstructible", "The case builder currently supports only one Markdown effect")
        for name in ("missing-section", "altered-section")
    ] + [
        (name, "not_applicable", "No skill effect declared")
        for name in (
            "missing-reference",
            "altered-reference",
            "altered-skill",
            "preserve-skill-backup",
            "stale-version",
            "stale-reference",
        )
    ] + [("missing-json-hook", "not_applicable", "No JSON hooks effect declared")]


@pytest.mark.parametrize("change", ["kind", "missing-body", "invalid-body", "extra"])
def test_altered_case_rejects_malformed_preparation(change: str) -> None:
    raw = json.loads(build_effect_cases(structured_spec(), context()).cases[2].to_json())
    preparation = raw["intermediate_preparation"]
    if change == "kind":
        preparation["kind"] = "unknown"
    elif change == "missing-body":
        del preparation["body"]
    elif change == "invalid-body":
        preparation["body"] = True
    else:
        preparation["extra"] = "unsupported"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize("root", ["home", "project"])
@pytest.mark.parametrize("markdown_count", [0, 1, 2])
def test_backup_preservation_case_follows_skill_across_effect_combinations(
    root: Literal["home", "project"], markdown_count: int
) -> None:
    skill = SkillEffect("package.md", "refs", Destination(root, "package"))
    markdown = tuple(
        MarkdownSectionEffect(
            f"source-{index}.md",
            Destination("project", f"GUIDE-{index}.md"),
            effect_id=f"markdown-{index}",
        )
        for index in range(markdown_count)
    )
    spec = EffectSpec((skill, *markdown))
    built = build_effect_cases(spec, context())
    assert [case.name for case in built.cases][-4:] == [
        "altered-skill",
        "preserve-skill-backup",
        "stale-version",
        "stale-reference",
    ]
    case = next(case for case in built.cases if case.name == "preserve-skill-backup")
    assert case.effects == spec
    assert case.operations == ["install", "install"]
    preparation = json.loads(case.to_json())["intermediate_preparation"]
    assert preparation["kind"] == "preserve-skill-backup"
    assert preparation["destination"] == {"root": root, "path": "package"}
    assert EffectInstallCase.from_json(case.to_json()) == case
    if markdown_count == 2:
        assert [(item.name, item.classification) for item in built.decisions] == [
            ("missing-section", "unconstructible"),
            ("altered-section", "unconstructible"),
            ("missing-json-hook", "not_applicable"),
        ]


def test_backup_preservation_retains_multiskill_construction_limit() -> None:
    spec = EffectSpec(
        (
            SkillEffect("first.md", "first-refs", Destination("home", "first")),
            SkillEffect(
                "second.md", "second-refs", Destination("project", "second"), effect_id="second"
            ),
        )
    )
    built = build_effect_cases(spec, context())
    assert not built.cases
    assert any(
        "Multiple skill effects" in d.reason
        for d in built.decisions
        if d.classification == "unconstructible"
    )


def test_removed_hook_timeout_rule_is_rejected() -> None:
    case = reinstall_case(structured_spec(), context())
    raw = json.loads(case.to_json())
    assert "hook_timeout" not in raw["subject"]["rules"]
    raw["subject"]["rules"]["hook_timeout"] = 10
    with pytest.raises(ValueError, match="Expected fields"):
        EffectInstallCase.from_json(json.dumps(raw))


def test_registry_rule_requires_boolean() -> None:
    rules = {
        "skill_lock": "persistent",
        "json_backup": ".graphify-bak",
        "skill_backup": ".bak",
        "json_registry": 0,
    }
    with pytest.raises(ValueError, match="registry rule"):
        EffectRules.from_data(rules)
