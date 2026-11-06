"""Ingestion has explicit structured expectations independent of case construction."""

from pathlib import Path

from tests.install_sandbox.component.contracts.test_effect_contracts import context
from tests.install_sandbox.component.host.native_support import FIXTURE
from tools.install_sandbox.contracts.effect_case import build_effect_cases
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.host.effect_reader import EffectSpecReader


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
    ]
    hooks = ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"]
    codebuddy = build_effect_cases(EffectSpecReader().read(specs / "codebuddy.yaml"), context())
    assert [case.name for case in codebuddy.cases] == common + hooks
    assert len(codebuddy.cases) == 11
    assert all(case.scope == "project" for case in codebuddy.cases)
    assert codebuddy.decisions == ()
    amp = build_effect_cases(EffectSpecReader().read(specs / "amp.yaml"), context())
    assert [case.name for case in amp.cases] == common
    assert len(amp.cases) == 8
    assert all(case.scope == "project" for case in amp.cases)
    assert [(item.name, item.classification, item.reason) for item in amp.decisions] == [
        (kind, "not_applicable", "No JSON hooks effect declared") for kind in hooks
    ]
