"""Agents uninstall requires an independently declared, exact command and composition."""

from dataclasses import replace
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_effect_cases,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.host.effect_reader import EffectSpecReader


def context() -> SubjectContext:
    return SubjectContext(
        "agents-subject",
        ("install", "--platform", "agents", "--project"),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        uninstall_invocation=("uninstall", "--platform", "agents", "--project"),
        uninstall_user_skill_path=".agents/skills/graphify",
    )


def spec_path(name: str = "agents") -> Path:
    return Path(__file__).resolve().parents[4] / f"tools/install_sandbox/specs/{name}.yaml"


def test_agents_uninstall_explicit_operations_and_preservation_witnesses() -> None:
    cases = build_effect_cases(EffectSpecReader().read(spec_path()), context()).cases
    case = cases[-1]
    assert case.name == "uninstall"
    assert case.operations == ["install", "uninstall"]
    assert case.second_phase == "uninstall"
    assert case.invocation_for("uninstall") == context().uninstall_invocation
    assert case.invocation_for("install") == context().invocation
    assert case.from_json(case.to_json()) == case
    witnesses = {(item["root"], item["path"]) for item in case.initial_files}
    assert {
        ("home", ".agents/skills/graphify/SKILL.md"),
        ("home", ".agents/skills/graphify/.graphify_version"),
        ("home", ".agents/skills/graphify/references/sandbox-user-witness.md"),
        ("project", ".agents/skills/graphify/personal.txt"),
        ("project", ".agents/skills/graphify/SKILL.md.bak"),
        ("project", "graphify-out/personal.txt"),
    } <= witnesses
    assert not any(root == "project" and "/references/" in path for root, path in witnesses)


def test_legacy_context_omits_optional_command_and_does_not_construct_uninstall() -> None:
    subject = replace(context(), uninstall_invocation=None, uninstall_user_skill_path=None)
    assert "uninstall_invocation" not in subject.to_data()
    cases = build_effect_cases(EffectSpecReader().read(spec_path()), subject).cases
    assert "uninstall" not in [case.name for case in cases]
    assert cases[0].second_phase == "reinstall"
    assert "uninstall_invocation" not in cases[0].to_json()
    with pytest.raises(ValueError, match="Unsupported subject operation"):
        cases[0].invocation_for("uninstall")


@pytest.mark.parametrize("name", ["amp", "user/agents"])
def test_uninstall_rejects_other_compositions(name: str) -> None:
    with pytest.raises(ValueError, match="Unsupported uninstall composition"):
        build_effect_cases(EffectSpecReader().read(spec_path(name)), context())


@pytest.mark.parametrize(
    "command",
    [
        ("uninstall",),
        ("uninstall", "--project"),
        ("uninstall", "--platform", "agents"),
        ("uninstall", "--platform", "agents", "--project", "--purge"),
    ],
)
def test_uninstall_rejects_untargeted_or_purge_commands(command: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="Unsupported uninstall composition"):
        build_effect_cases(
            EffectSpecReader().read(spec_path()), replace(context(), uninstall_invocation=command)
        )


def test_uninstall_uses_declared_skill_data_without_target_name_dispatch() -> None:
    spec = EffectSpec(
        (SkillEffect("custom.md", "custom-refs", Destination("project", "custom/skill")),)
    )
    subject = replace(
        context(),
        invocation=("install", "--platform", "custom", "--project"),
        uninstall_invocation=("uninstall", "--platform", "custom", "--project"),
        uninstall_user_skill_path="user/skill",
    )
    case = build_effect_cases(spec, subject).cases[-1]
    assert case.name == "uninstall"
    witnesses = {(item["root"], item["path"]) for item in case.initial_files}
    assert ("project", "custom/skill/SKILL.md.bak") in witnesses
    assert ("home", "user/skill/SKILL.md") in witnesses


def test_uninstall_requires_explicit_home_path() -> None:
    with pytest.raises(ValueError, match="command and HOME skill path together"):
        build_effect_cases(
            EffectSpecReader().read(spec_path()), replace(context(), uninstall_user_skill_path=None)
        )


def grouped_context() -> SubjectContext:
    commands = (
        ("install", "--platform", "agents"),
        ("install", "--platform", "agents", "--project"),
        ("install", "--platform", "copilot", "--project"),
    )
    return replace(
        context(),
        invocation=commands[0],
        group_install_invocations=commands,
        uninstall_invocation=("uninstall", "--project"),
        uninstall_user_skill_path=None,
    )


def test_group_uninstall_constructs_ordered_commands_and_roundtrips() -> None:
    spec = EffectSpecReader().read(spec_path("group-uninstall-project"))
    built = build_effect_cases(spec, grouped_context(), "arbitrary-target")
    assert len(built.entries) == 1
    case = built.cases[0]
    assert case.name == "group-uninstall-project"
    commands = grouped_context().group_install_invocations
    assert commands is not None
    assert [case.invocation_for(operation) for operation in case.operations] == [
        *commands,
        ("uninstall", "--project"),
    ]
    assert case.second_phase == "uninstall"
    assert case.from_json(case.to_json()) == case
    files = {(item["root"], item["path"]) for item in case.initial_files}
    assert ("project", "graphify-out/personal.txt") in files
    for effect in spec.effects:
        assert (effect.destination.root, effect.destination.path + "/personal.txt") in files
    assert not any(path.endswith(("SKILL.md", ".graphify_version")) for _, path in files)


@pytest.mark.parametrize("mutation", ["missing-command", "purge", "wrong-root"])
def test_group_uninstall_rejects_incomplete_or_unsafe_declarations(mutation: str) -> None:
    spec = EffectSpecReader().read(spec_path("group-uninstall-project"))
    subject = grouped_context()
    if mutation == "missing-command":
        assert subject.group_install_invocations is not None
        subject = replace(subject, group_install_invocations=subject.group_install_invocations[:2])
    elif mutation == "purge":
        subject = replace(subject, uninstall_invocation=("uninstall", "--project", "--purge"))
    else:
        first = spec.effects[0]
        assert isinstance(first, SkillEffect)
        spec = replace(
            spec,
            effects=(
                replace(first, destination=Destination("project", "other/skill")),
                *spec.effects[1:],
            ),
        )
    with pytest.raises(ValueError):
        build_effect_cases(spec, subject)


def test_reinstall_constructor_rejects_grouped_context() -> None:
    spec = EffectSpecReader().read(spec_path("group-uninstall-project"))
    with pytest.raises(ValueError, match="Grouped operations require"):
        build_reinstall_case(spec, grouped_context())


def global_context() -> SubjectContext:
    commands = (("install", "--platform", "agents"), ("install", "--platform", "copilot"))
    return replace(
        grouped_context(),
        invocation=commands[0],
        group_install_invocations=commands,
        uninstall_invocation=("uninstall",),
        purge_invocation=("uninstall", "--purge"),
        home_lock_destinations=(".agents/skills/graphify", ".copilot/skills/graphify"),
    )


def test_global_pair_shares_state_and_declares_exact_commands() -> None:
    spec = EffectSpecReader().read(spec_path("global-uninstall"))
    ordinary, purge = build_effect_cases(spec, global_context()).cases
    assert [ordinary.name, purge.name] == ["global-uninstall", "global-uninstall-purge"]
    assert ordinary.initial_files == purge.initial_files
    assert ordinary.step_phases == ("install", "install-user-2", "uninstall")
    assert purge.step_phases == ("install", "install-user-2", "purge")
    for case, final in ((ordinary, ("uninstall",)), (purge, ("uninstall", "--purge"))):
        assert [case.invocation_for(op) for op in case.operations] == [
            ("install", "--platform", "agents"),
            ("install", "--platform", "copilot"),
            final,
        ]
        assert case.from_json(case.to_json()) == case
    files = {(item["root"], item["path"]) for item in ordinary.initial_files}
    assert {
        ("project", "graphify-out/personal.txt"),
        ("project", "graphify-out/nested/result.json"),
        ("project", "personal-next-to-output.txt"),
    } <= files
    for effect in spec.effects:
        assert ("home", effect.destination.path + "/personal.txt") in files
        assert ("project", effect.destination.path + "/personal.txt") in files
        assert any(
            root == "home"
            and path.startswith(str(Path(effect.destination.path).parent))
            and not path.startswith(effect.destination.path + "/")
            for root, path in files
        )


def test_global_purge_is_explicit_and_ordinary_multiskill_stays_unavailable() -> None:
    spec = EffectSpecReader().read(spec_path("global-uninstall"))
    subject = replace(global_context(), purge_invocation=None)
    with pytest.raises(ValueError, match="Unsupported global uninstall composition"):
        build_effect_cases(spec, subject)
    with pytest.raises(ValueError, match="Multiple skill effects"):
        build_effect_cases(
            spec,
            replace(
                subject,
                group_install_invocations=None,
                uninstall_invocation=None,
                home_lock_destinations=(),
            ),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"purge_invocation": ("uninstall", "--project", "--purge")},
        {"uninstall_invocation": ("uninstall", "--platform", "agents")},
        {"group_install_invocations": (("install", "--platform", "agents"),) * 2},
        {"home_lock_destinations": ("../unsafe",)},
        {"home_lock_destinations": ("same", "same")},
    ],
)
def test_global_rejects_inconsistent_commands_and_locks(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        build_effect_cases(
            EffectSpecReader().read(spec_path("global-uninstall")),
            replace(global_context(), **change),
        )


def test_global_context_roundtrips_optional_locks_in_all_three_roots() -> None:
    subject = replace(
        global_context(),
        group_lock_destinations=(".kiro/skills/graphify",),
        config_lock_destinations=("claude_config_dir/skills/graphify",),
    )
    cases = build_effect_cases(
        EffectSpecReader().read(spec_path("global-uninstall")), subject
    ).cases
    for case in cases:
        restored = case.from_json(case.to_json()).subject
        assert restored.group_lock_destinations == (".kiro/skills/graphify",)
        assert restored.home_lock_destinations == (
            ".agents/skills/graphify",
            ".copilot/skills/graphify",
        )
        assert restored.config_lock_destinations == ("claude_config_dir/skills/graphify",)
