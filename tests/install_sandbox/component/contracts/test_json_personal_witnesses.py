"""Personal JSON witnesses never alias managed member identities."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.contracts.test_effect_contracts import context
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import build_effect_cases, seeded_json_hook_group
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, JsonHooksEffect
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.host.result_reader import read_evidence

COMMAND = "python personal_graphify_audit.py"


def collision_spec() -> EffectSpec:
    commands = (
        COMMAND,
        COMMAND + ".sandbox-1",
        "python personal_after_read.py",
        "python personal_neighbor.py",
        "python personal_duplicate_a.py",
        "python personal_duplicate_b.py",
    )
    return EffectSpec(
        (
            JsonHooksEffect(
                Destination("project", "settings.json"),
                tuple(
                    HookExpectation(
                        str(index),
                        "PreToolUse",
                        "Bash|Grep",
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 17,
                        },
                    )
                    for index, command in enumerate(commands)
                ),
            ),
        )
    )


def _document_hooks(content: str) -> list[dict[str, Any]]:
    data = cast(dict[str, Any], json.loads(content))
    return [
        hook for groups in data["hooks"].values() for group in groups for hook in group["hooks"]
    ]


def test_all_seed_variants_avoid_every_declared_member_and_reconstruct_identically() -> None:
    spec = collision_spec()
    reserved = {
        hook.content["command"]
        for effect in spec.effects
        if isinstance(effect, JsonHooksEffect)
        for hook in effect.hooks
    }
    cases = build_effect_cases(spec, context()).cases
    for case in cases:
        for initial in case.initial_files:
            if initial["path"] != "settings.json":
                continue
            managed = [
                hook for hook in _document_hooks(initial["content"]) if hook["command"] in reserved
            ]
            # Only the explicitly selected managed object may be seeded.
            assert len(managed) == (
                1 if case.key.member is not None and initial["root"] == "project" else 0
            )
        if case.key.member is not None:
            effect = spec.effects[0]
            assert isinstance(effect, JsonHooksEffect)
            member = next(hook for hook in effect.hooks if hook.id == case.key.member)
            target = next(
                item
                for item in case.initial_files
                if item["root"] == "project" and item["path"] == "settings.json"
            )
            seeded = json.loads(target["content"])["hooks"][member.event][0]
            assert seeded == seeded_json_hook_group(effect, member, spec)
            assert seeded["hooks"][1]["command"] == COMMAND + ".sandbox-2"


@pytest.mark.parametrize(
    "operation", ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"]
)
def test_collision_member_repairs_and_replays_without_consuming_personal_hook(
    tmp_path: Path,
    operation: str,
) -> None:
    effect = collision_spec().effects[0]
    assert isinstance(effect, JsonHooksEffect)
    spec = EffectSpec((replace(effect, hooks=(effect.hooks[0],)),))
    case = next(c for c in build_effect_cases(spec, context()).cases if c.name == operation)
    case.write(tmp_path / "case.json")
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "METADATA").write_text("Version: 1\n")

    proof = tmp_path / "proof"
    result = InstallTestRunner(InstallerDriver(_install_collision)).run_case(
        reference_sources=sources,
        prepared_executable=tmp_path / "installer",
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=proof,
    )
    assert result.status == "passed"
    assert read_evidence(proof) == result


def _install_collision(
    args: list[str], project: Path, environment: dict[str, str], timeout: float
) -> InstallerCommandResult:
    path = project / "settings.json"
    backup = project / "settings.json.graphify-bak"
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    data = cast(dict[str, Any], json.loads(path.read_text()))
    groups = data["hooks"]["PreToolUse"]
    matching = [group for group in groups if group["matcher"] == "Bash|Grep"]
    found = False
    for group in matching:
        repaired: list[dict[str, object]] = []
        for hook in group["hooks"]:
            if hook.get("command") == COMMAND and hook.get("type") == "command":
                if not found:
                    repaired.append({"type": "command", "command": COMMAND, "timeout": 17})
                    found = True
            else:
                repaired.append(hook)
        group["hooks"] = repaired
    if not found:
        matching[0]["hooks"].append({"type": "command", "command": COMMAND, "timeout": 17})
    path.write_text(json.dumps(data) + "\n")
    return InstallerCommandResult(args, str(project), "completed", 0, None)


def test_other_effect_members_reserve_commands_without_changing_noncolliding_defaults() -> None:
    original = collision_spec()
    effect = original.effects[0]
    assert isinstance(effect, JsonHooksEffect)
    other = replace(
        effect,
        effect_id="other",
        destination=Destination("home", "other.json"),
        hooks=(
            replace(
                effect.hooks[0],
                content={"type": "command", "command": COMMAND + ".sandbox-2", "timeout": 17},
            ),
        ),
    )
    spec = EffectSpec((*original.effects, other))
    assert (
        cast(
            list[dict[str, object]], seeded_json_hook_group(effect, effect.hooks[0], spec)["hooks"]
        )[1]["command"]
        == COMMAND + ".sandbox-3"
    )
    plain = replace(
        effect,
        hooks=(replace(effect.hooks[0], content={"type": "command", "command": "graphify run"}),),
    )
    assert cast(
        list[dict[str, object]],
        seeded_json_hook_group(plain, plain.hooks[0], EffectSpec((plain,)))["hooks"],
    )[1] == {
        "type": "command",
        "command": COMMAND,
        "timeout": 17,
    }
