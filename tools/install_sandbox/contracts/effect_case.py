"""Construct a reinstall case directly from effects and explicit subject rules."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from tools.install_sandbox.contracts.effects import (
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
    physical_destinations,
)
from tools.install_sandbox.contracts.spec import fields, relative_path, text


class InitialFile(TypedDict):
    root: str
    path: str
    content: str


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate case transport field")
        result[key] = value
    return result


@dataclass(frozen=True)
class EffectRules:
    hook_timeout: int
    skill_lock: str
    json_backup: str
    skill_backup: str
    json_registry: bool

    @classmethod
    def from_data(cls, value: object) -> "EffectRules":
        data = fields(value, "hook_timeout skill_lock json_backup skill_backup json_registry")
        if type(data["hook_timeout"]) is not int or type(data["json_registry"]) is not bool:
            raise ValueError("Expected explicit hook timeout and registry rules")
        return cls(
            data["hook_timeout"],
            text(data["skill_lock"]),
            text(data["json_backup"]),
            text(data["skill_backup"]),
            data["json_registry"],
        )


@dataclass(frozen=True)
class SubjectContext:
    identity: str
    invocation: tuple[str, ...]
    version_source: str
    rules: EffectRules

    @classmethod
    def from_data(cls, value: object) -> "SubjectContext":
        data = fields(value, "identity invocation version_source rules")
        raw = data["invocation"]
        if not isinstance(raw, list) or not raw:
            raise ValueError("Expected explicit subject invocation arguments")
        arguments = tuple(text(item) for item in cast(list[object], raw))
        if any("\x00" in arg for arg in arguments):
            raise ValueError("Invalid invocation argument")
        return cls(
            text(data["identity"]),
            arguments,
            relative_path(data["version_source"]),
            EffectRules.from_data(data["rules"]),
        )


def _validate_hook_rules(effect: JsonHooksEffect, rules: EffectRules) -> None:
    if (
        type(rules.hook_timeout) is not int
        or rules.hook_timeout != 10
        or rules.json_backup != ".graphify-bak"
        or rules.json_registry is not False
    ):
        raise ValueError("Unsupported or missing JSON hooks reinstall rule")
    if any(
        type(hook.content.get("timeout")) is not int
        or hook.content["timeout"] != rules.hook_timeout
        for hook in effect.hooks
    ):
        raise ValueError("Hook timeout contradicts explicit subject rule")


def _validate_rules(spec: EffectSpec, subject: SubjectContext) -> None:
    rules = subject.rules
    if sum(isinstance(effect, SkillEffect) for effect in spec.effects) > 1:
        raise ValueError("Multiple skill effects require unavailable lock observation capability")
    for effect in spec.effects:
        if isinstance(effect, SkillEffect) and (
            rules.skill_lock != "persistent" or rules.skill_backup != ".bak"
        ):
            raise ValueError("Unsupported or missing skill reinstall rule")
        if isinstance(effect, JsonHooksEffect):
            _validate_hook_rules(effect, rules)


def _witness_available(
    root: str, path: str, spec: EffectSpec, occupied: set[tuple[str, str]]
) -> bool:
    candidate = PurePosixPath(path)
    reserved = [
        (item.root, item.path) for effect in spec.effects for item in physical_destinations(effect)
    ] + list(occupied)
    return all(
        root != other_root
        or not (
            candidate == PurePosixPath(other)
            or candidate in PurePosixPath(other).parents
            or PurePosixPath(other) in candidate.parents
        )
        for other_root, other in reserved
    )


def effect_initial_files(spec: EffectSpec) -> list[InitialFile]:
    """Compose independent personal documents around each actual destination."""
    files: list[InitialFile] = []
    occupied = {(effect.destination.root, effect.destination.path) for effect in spec.effects}
    for index, effect in enumerate(spec.effects):
        destination = effect.destination
        if isinstance(effect, MarkdownSectionEffect):
            content = "# My project\n\n## Language\nRespond in English.\n"
        elif isinstance(effect, JsonHooksEffect):
            content = (
                json.dumps(
                    {
                        "theme": "dark",
                        "metadata": {"owner": "personal"},
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash|Grep",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python personal_graphify_audit.py",
                                            "timeout": 17,
                                        }
                                    ],
                                }
                            ],
                            "PostToolUse": [
                                {
                                    "matcher": "Read",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python personal_after_read.py",
                                            "timeout": 9,
                                        }
                                    ],
                                }
                            ],
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            content = ""
        if content:
            files.append({"root": destination.root, "path": destination.path, "content": content})
        parent = PurePosixPath(destination.path).parent
        witness = str(parent / f"personal-effect-{index}.txt")
        while not _witness_available(destination.root, witness, spec, occupied):
            witness = f"sandbox-personal-{index}-" + PurePosixPath(witness).name
        occupied.add((destination.root, witness))
        files.append(
            {
                "root": destination.root,
                "path": witness,
                "content": "Personal document to preserve.\n",
            }
        )
        opposite = "project" if destination.root == "home" else "home"
        if not isinstance(effect, SkillEffect) and _witness_available(
            opposite, destination.path, spec, occupied
        ):
            occupied.add((opposite, destination.path))
            files.append({"root": opposite, "path": destination.path, "content": content})
    return files


@dataclass(frozen=True)
class EffectInstallCase:
    name: str
    target: str
    scope: str
    effects: EffectSpec
    subject: SubjectContext
    initial_files: list[InitialFile]
    operations: list[str]

    def to_json(self) -> str:
        data = asdict(self)
        data["format"] = "explicit-expectations-v2"
        data["effects"] = self.effects.to_data()
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        self.from_json(payload)
        return payload

    def write(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8", newline="\n")

    @classmethod
    def from_json(cls, payload: str) -> "EffectInstallCase":
        data = fields(
            json.loads(payload, object_pairs_hook=unique_object),
            "format name target scope effects subject initial_files operations",
        )
        if data["format"] != "explicit-expectations-v2" or data["name"] != "reinstall":
            raise ValueError("Unsupported effects case format or operation")
        case = build_reinstall_case(
            EffectSpec.from_data(data["effects"]),
            SubjectContext.from_data(data["subject"]),
            text(data["target"]),
        )
        if (
            data["scope"] != case.scope
            or data["operations"] != case.operations
            or data["initial_files"] != case.initial_files
        ):
            raise ValueError("Effects case preparation or operations do not match definition")
        return case


def build_reinstall_case(
    spec: EffectSpec, subject: SubjectContext, target: str = "controlled"
) -> EffectInstallCase:
    # Round-trip both boundaries even for Python callers; invalid dataclasses are not trusted.
    spec = EffectSpec.from_data(spec.to_data())
    subject = SubjectContext.from_data(json.loads(json.dumps(asdict(subject))))
    _validate_rules(spec, subject)
    return EffectInstallCase(
        "reinstall",
        text(target),
        "project",
        spec,
        subject,
        effect_initial_files(spec),
        ["install", "install"],
    )
