"""Ingestion has explicit structured expectations independent of case construction."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import FIXTURE
from tools.install_sandbox.contracts.effect_case import (
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


def context() -> SubjectContext:
    return SubjectContext(
        "controlled-fixture",
        ("controlled", "install"),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
    )


def test_generic_effect_fixture_has_exact_structured_representation() -> None:
    assert EffectSpecReader().read(FIXTURE) == EffectSpec(
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
                        {
                            "type": "command",
                            "command": "graphify hook-guard search",
                            "timeout": 10,
                        },
                    ),
                    HookExpectation(
                        "PreToolUse-read",
                        "PreToolUse",
                        "Read|Glob",
                        {
                            "type": "command",
                            "command": "graphify hook-guard read",
                            "timeout": 10,
                        },
                    ),
                ),
            ),
        )
    )


def test_active_amp_spec_has_project_skill_and_markdown_without_hooks() -> None:
    active = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/amp.yaml"
    assert EffectSpecReader().read(active) == EffectSpec(
        (
            SkillEffect(
                "skill-amp.md",
                "skills/amp/references",
                Destination("project", ".agents/skills/graphify"),
            ),
            MarkdownSectionEffect("always_on/agents-md.md", Destination("project", "AGENTS.md")),
        )
    )


def test_active_codebuddy_spec_has_current_retained_target_facts() -> None:
    active = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/codebuddy.yaml"
    spec = EffectSpecReader().read(active)
    assert [effect.destination for effect in spec.effects] == [
        Destination("home", ".codebuddy/skills/graphify"),
        Destination("project", "CODEBUDDY.md"),
        Destination("project", ".codebuddy/settings.json"),
    ]
    skill, markdown, hooks = spec.effects
    assert isinstance(skill, SkillEffect)
    assert skill.source == "skill.md" and skill.references == "skills/claude/references"
    assert isinstance(markdown, MarkdownSectionEffect)
    assert markdown.source == "always_on/claude-md.md" and markdown.marker == "## graphify"
    assert isinstance(hooks, JsonHooksEffect)
    assert [(hook.matcher, hook.content["command"]) for hook in hooks.hooks] == [
        ("Bash|Grep", "graphify hook-guard search"),
        ("Read|Glob", "graphify hook-guard read"),
    ]


def test_active_project_specs_construct_supported_cases_without_running_installer() -> None:
    specs = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs"
    common = [
        "reinstall",
        "missing-section",
        "altered-section",
        "missing-reference",
        "altered-reference",
        "altered-skill",
        "preserve-skill-backup",
        "stale-version",
        "stale-reference",
        "stale-references-tmp",
    ]
    hooks = ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"]
    codebuddy = build_effect_cases(EffectSpecReader().read(specs / "codebuddy.yaml"), context())
    assert [case.name for case in codebuddy.cases] == common + hooks
    assert len(codebuddy.cases) == 13
    assert all(case.scope == "project" for case in codebuddy.cases)
    assert codebuddy.decisions == ()
    amp = build_effect_cases(EffectSpecReader().read(specs / "amp.yaml"), context())
    assert [case.name for case in amp.cases] == common
    assert len(amp.cases) == 10
    assert all(case.scope == "project" for case in amp.cases)
    assert [(item.name, item.classification, item.reason) for item in amp.decisions] == [
        (kind, "not_applicable", "No JSON hooks effect declared") for kind in hooks
    ]


@pytest.mark.parametrize(
    ("target", "source", "references", "destination"),
    [
        ("agents", "skill-agents.md", "skills/agents/references", ".agents/skills/graphify"),
        ("copilot", "skill-copilot.md", "skills/copilot/references", ".copilot/skills/graphify"),
        ("kimi", "skill.md", "skills/claude/references", ".kimi/skills/graphify"),
        ("pi", "skill-pi.md", "skills/pi/references", ".pi/agent/skills/graphify"),
    ],
)
@pytest.mark.parametrize("scope", ["project", "user"])
def test_active_skill_only_spec_has_exact_representation(
    target: str,
    source: str,
    references: str,
    destination: str,
    scope: str,
) -> None:
    specs = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs"
    active = specs / ("user" if scope == "user" else "") / f"{target}.yaml"
    spec = EffectSpecReader().read(active)
    assert spec == EffectSpec(
        (
            SkillEffect(
                source,
                references,
                Destination("home" if scope == "user" else "project", destination),
            ),
        ),
        scope,
    )
    construction = build_effect_cases(spec, context())
    assert [case.name for case in construction.cases] == [
        "reinstall",
        "missing-reference",
        "altered-reference",
        "altered-skill",
        "preserve-skill-backup",
        "stale-version",
        "stale-reference",
        "stale-references-tmp",
    ]
    assert all(case.scope == scope for case in construction.cases)
    assert [(item.name, item.classification, item.reason) for item in construction.decisions] == [
        ("missing-section", "not_applicable", "No Markdown effect declared"),
        ("altered-section", "not_applicable", "No Markdown effect declared"),
        ("missing-json-hook", "not_applicable", "No JSON hooks effect declared"),
        ("altered-json-hook", "not_applicable", "No JSON hooks effect declared"),
        ("duplicate-json-hook", "not_applicable", "No JSON hooks effect declared"),
    ]
