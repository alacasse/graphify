"""Construct a reinstall case directly from effects and explicit subject rules."""

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal, TypedDict, cast

from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
    physical_destinations,
)
from tools.install_sandbox.contracts.intermediate import (
    AlteredReferencePreparation,
    AlteredSkillPreparation,
    IntermediatePreparation,
    JsonHookPreparation,
    MissingReferencePreparation,
    PreserveSkillBackupPreparation,
    StaleReferencePreparation,
    StaleReferencesTmpPreparation,
    StaleVersionPreparation,
    preparation_from_data,
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
class GroupInstall:
    invocation: tuple[str, ...]
    destination: Destination

    def __post_init__(self) -> None:
        command = self.invocation
        suffix = ("--project",) if self.destination.root == "project" else ()
        if (
            len(command) != 3 + len(suffix)
            or command[:2] != ("install", "--platform")
            or re.fullmatch(r"[a-z][a-z0-9-]*", command[2]) is None
            or command[3:] != suffix
        ):
            raise ValueError("Unsupported grouped install command")

    def to_data(self) -> dict[str, object]:
        return {
            "invocation": list(self.invocation),
            "destination": {"root": self.destination.root, "path": self.destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "GroupInstall":
        data = fields(value, "invocation destination")
        invocation = _optional_invocation(data["invocation"])
        if invocation is None:
            raise ValueError("Grouped install requires an explicit invocation")
        return cls(invocation, Destination.from_data(data["destination"]))


@dataclass(frozen=True)
class SubjectContext:
    identity: str
    invocation: tuple[str, ...]
    version_source: str
    rules: EffectRules
    package_root: str | None = None
    revision: str | None = None
    uninstall_invocation: tuple[str, ...] | None = None
    uninstall_user_skill_path: str | None = None
    group_installs: tuple[GroupInstall, ...] | None = None

    group_lock_destinations: tuple[str, ...] = ()
    purge_invocation: tuple[str, ...] | None = None
    home_lock_destinations: tuple[str, ...] = ()
    config_lock_destinations: tuple[str, ...] = ()

    def to_data(self) -> dict[str, object]:
        data = cast(dict[str, object], json.loads(json.dumps(asdict(self))))
        if self.uninstall_invocation is None:
            data.pop("uninstall_invocation")
        if self.uninstall_user_skill_path is None:
            data.pop("uninstall_user_skill_path")
        if self.group_installs is None:
            data.pop("group_installs")
        if not self.group_lock_destinations:
            data.pop("group_lock_destinations")
        if self.purge_invocation is None:
            data.pop("purge_invocation")
        if not self.home_lock_destinations:
            data.pop("home_lock_destinations")
        if not self.config_lock_destinations:
            data.pop("config_lock_destinations")
        return data

    @classmethod
    def from_data(cls, value: object) -> "SubjectContext":
        data = _context_fields(value)
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
            cast(str | None, data["package_root"]),
            cast(str | None, data["revision"]),
            _optional_invocation(data["uninstall_invocation"]),
            cast(str | None, data["uninstall_user_skill_path"]),
            _group_installs(data["group_installs"]),
            _group_lock_destinations(data),
            _optional_invocation(data["purge_invocation"]),
            _lock_destinations(data, "home_lock_destinations"),
            _lock_destinations(data, "config_lock_destinations"),
        )


def _optional_invocation(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("Expected explicit uninstall invocation arguments")
    arguments = tuple(text(item) for item in cast(list[object], value))
    if any("\x00" in argument for argument in arguments):
        raise ValueError("Invalid uninstall invocation argument")
    return arguments


def _group_installs(value: object) -> tuple[GroupInstall, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("Grouped uninstall requires at least one install command")
    return tuple(GroupInstall.from_data(item) for item in cast(list[object], value))


def _group_lock_destinations(data: dict[str, object]) -> tuple[str, ...]:
    return _lock_destinations(data, "group_lock_destinations")


def _lock_destinations(data: dict[str, object], field: str) -> tuple[str, ...]:
    raw = data[field]
    if not isinstance(raw, list):
        raise ValueError("Expected a list of project skill lock destinations")
    paths = tuple(relative_path(item) for item in cast(list[object], raw))
    if paths and (data["group_installs"] is None or len(set(paths)) != len(paths)):
        raise ValueError("Group lock destinations require a grouped case and unique paths")
    return paths


def _context_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a subject context object")
    incoming = cast(dict[str, object], value)
    data = fields(
        {
            "package_root": None,
            "revision": None,
            "uninstall_invocation": None,
            "uninstall_user_skill_path": None,
            "group_installs": None,
            "group_lock_destinations": [],
            "home_lock_destinations": [],
            "config_lock_destinations": [],
            "purge_invocation": None,
            **incoming,
        },
        "identity invocation version_source rules package_root revision uninstall_invocation "
        "uninstall_user_skill_path group_installs group_lock_destinations "
        "purge_invocation home_lock_destinations config_lock_destinations",
    )
    if data["group_installs"] is None and (
        (data["uninstall_invocation"] is None) != (data["uninstall_user_skill_path"] is None)
    ):
        raise ValueError("Uninstall requires an explicit command and HOME skill path together")
    if data["uninstall_user_skill_path"] is not None:
        relative_path(data["uninstall_user_skill_path"])
    if data["purge_invocation"] is not None and data["group_installs"] is None:
        raise ValueError("Purge invocation requires an explicit global grouped case")
    root, revision = data["package_root"], data["revision"]
    if root is not None:
        relative_path(root)
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError("Package preparation requires an exact subject commit SHA")
    elif revision is not None:
        raise ValueError("Subject revision requires a package root")
    return data


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
    if (
        subject.group_installs is None
        and sum(isinstance(effect, SkillEffect) for effect in spec.effects) > 1
    ):
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


def _output_witness(files: list[InitialFile], preferred: str, content: str) -> InitialFile:
    """Choose an output test file alongside the other declared personal files."""
    occupied = {PurePosixPath(item["path"]) for item in files if item["root"] == "project"}
    candidate = PurePosixPath(preferred)
    path = candidate
    index = 0
    while path in occupied or any(path in other.parents for other in occupied):
        index += 1
        path = candidate.with_name(f"sandbox-{index}-{candidate.name}")
    return {"root": "project", "path": str(path), "content": content}


def effect_initial_files(
    spec: EffectSpec, *, project_skill_witnesses: bool = True
) -> list[InitialFile]:
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
    if project_skill_witnesses and spec.scope == "user" and len(spec.effects) == 1:
        files.extend(_project_skill_witnesses(spec))
    return files


def _project_skill_witnesses(spec: EffectSpec) -> list[InitialFile]:
    """Seed a distinct project installation that HOME installation must leave intact."""
    effect = spec.effects[0]
    assert isinstance(effect, SkillEffect)
    path = effect.destination.path
    documents = {
        path + "/SKILL.md": "# Project skill witness\nPreserve this project installation.\n",
        path + "/references/sandbox-project-witness.md": "Project reference witness.\n",
        path + "/.graphify_version": "project-witness-version\n",
        path + "/personal.txt": "Personal project skill content.\n",
    }
    occupied = {("project", name) for name in documents}
    instructions = "AGENTS.md"
    while not _witness_available("project", instructions, spec, occupied):
        instructions = "sandbox-project-" + instructions
    documents[instructions] = "# Personal project instructions\nPreserve these instructions.\n"
    return [
        {"root": "project", "path": name, "content": content} for name, content in documents.items()
    ]


def seeded_json_hook_group(effect: JsonHooksEffect) -> dict[str, object]:
    """Independent cohabitation witness for the first declared hook."""
    return {
        "matcher": effect.hooks[0].matcher,
        "sandbox_personal": "preserve",
        "hooks": [
            dict(effect.hooks[0].content),
            {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17},
        ],
    }


def _json_hook_case(
    reinstall: "EffectInstallCase", effect: JsonHooksEffect, kind: str
) -> "EffectInstallCase":
    neighbor: dict[str, object] = {
        "matcher": "SandboxPersonalNeighbor",
        "sandbox_neighbor": True,
        "hooks": [{"type": "command", "command": "python personal_neighbor.py", "timeout": 23}],
    }
    groups = [seeded_json_hook_group(effect)]
    if kind == "duplicate-json-hook":
        groups.append(
            {
                "matcher": effect.hooks[0].matcher,
                "sandbox_personal": "duplicate-destination",
                "hooks": [
                    {"type": "command", "command": "python personal_duplicate_a.py", "timeout": 19},
                    {"type": "command", "command": "python personal_duplicate_b.py", "timeout": 29},
                ],
            }
        )
    groups.append(neighbor)
    settings = {
        "theme": "dark",
        "metadata": {"owner": "personal"},
        "hooks": {effect.hooks[0].event: groups},
    }
    initial = [dict(item) for item in reinstall.initial_files]
    for item in initial:
        if (item["root"], item["path"]) == (effect.destination.root, effect.destination.path):
            item["content"] = json.dumps(settings, indent=2) + "\n"
    return replace(
        reinstall,
        name=kind,
        initial_files=initial,
        intermediate_preparation=JsonHookPreparation(effect.destination, kind),
    )


@dataclass(frozen=True)
class EffectInstallCase:
    name: str
    target: str
    scope: str
    effects: EffectSpec
    subject: SubjectContext
    initial_files: list[InitialFile]
    operations: list[str]
    intermediate_preparation: (
        IntermediatePreparation
        | MissingReferencePreparation
        | JsonHookPreparation
        | AlteredReferencePreparation
        | AlteredSkillPreparation
        | PreserveSkillBackupPreparation
        | StaleVersionPreparation
        | StaleReferencePreparation
        | StaleReferencesTmpPreparation
        | None
    ) = None

    @property
    def second_phase(self) -> Literal["reinstall", "uninstall", "purge"]:
        if self.operations[-1] in {"uninstall", "purge"}:
            return cast(Literal["uninstall", "purge"], self.operations[-1])
        return "reinstall"

    @property
    def group_skills(self) -> tuple[SkillEffect, ...]:
        installs = self.subject.group_installs
        if installs is None:
            return ()
        skills = {
            effect.destination: effect
            for effect in self.effects.effects
            if isinstance(effect, SkillEffect)
        }
        return tuple(skills[install.destination] for install in installs)

    @property
    def step_phases(self) -> tuple[str, ...]:
        if self.subject.group_installs is not None:
            return tuple(self.operations)
        return ("install", self.second_phase)

    def invocation_for(self, operation: str) -> tuple[str, ...]:
        if self.subject.group_installs is not None:
            for index, install in enumerate(self.subject.group_installs):
                if operation == ("install" if index == 0 else f"install-group-{index}"):
                    return install.invocation
        if operation == "install":
            return self.subject.invocation
        if operation == "uninstall" and self.subject.uninstall_invocation is not None:
            return self.subject.uninstall_invocation
        if operation == "purge" and self.subject.purge_invocation is not None:
            return self.subject.purge_invocation
        raise ValueError(f"Unsupported subject operation: {operation}")

    def to_json(self) -> str:
        data = asdict(self)
        data["subject"] = self.subject.to_data()
        data["format"] = "explicit-expectations-v9"
        data["intermediate_preparation"] = (
            None
            if self.intermediate_preparation is None
            else self.intermediate_preparation.to_data()
        )
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
            "format name target scope effects subject initial_files operations "
            "intermediate_preparation",
        )
        if data["format"] != "explicit-expectations-v9":
            raise ValueError("Unsupported effects case format or operation")
        builds = build_effect_cases(
            EffectSpec.from_data(data["effects"]),
            SubjectContext.from_data(data["subject"]),
            text(data["target"]),
        )
        matches = [case for case in builds.cases if case.name == data["name"]]
        if not matches:
            raise ValueError("Unsupported effects case")
        case = matches[0]
        preparation = data["intermediate_preparation"]
        parsed = None if preparation is None else preparation_from_data(preparation)
        if (
            parsed != case.intermediate_preparation
            or data["scope"] != case.scope
            or data["operations"] != case.operations
            or data["initial_files"] != case.initial_files
        ):
            raise ValueError("Effects case preparation or operations do not match definition")
        return case


def _validated_inputs(
    spec: EffectSpec, subject: SubjectContext
) -> tuple[EffectSpec, SubjectContext]:
    # Round-trip both boundaries even for Python callers; invalid dataclasses are not trusted.
    spec = EffectSpec.from_data(spec.to_data())
    subject = SubjectContext.from_data(json.loads(json.dumps(asdict(subject))))
    _validate_rules(spec, subject)
    return spec, subject


def build_reinstall_case(
    spec: EffectSpec, subject: SubjectContext, target: str = "controlled"
) -> EffectInstallCase:
    spec, subject = _validated_inputs(spec, subject)
    if subject.group_installs is not None:
        raise ValueError("Grouped operations require a grouped case")
    return EffectInstallCase(
        "reinstall",
        text(target),
        spec.scope,
        spec,
        subject,
        effect_initial_files(spec),
        ["install", "install"],
    )


@dataclass(frozen=True)
class CaseNonConstruction:
    name: str
    classification: Literal["not_applicable", "unconstructible"]
    reason: str

    def __post_init__(self) -> None:
        text(self.name)
        text(self.reason)
        if self.classification not in {"not_applicable", "unconstructible"}:
            raise ValueError("Invalid case non-construction classification")


@dataclass(frozen=True)
class EffectCaseBuild:
    entries: tuple[EffectInstallCase | CaseNonConstruction, ...]

    def __post_init__(self) -> None:
        names = [entry.name for entry in self.entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate campaign case name")

    @property
    def cases(self) -> tuple[EffectInstallCase, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, EffectInstallCase))

    @property
    def decisions(self) -> tuple[CaseNonConstruction, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, CaseNonConstruction))


def build_effect_cases(
    spec: EffectSpec, subject: SubjectContext, target: str = "controlled"
) -> EffectCaseBuild:
    """Derive cases and construction decisions in campaign order."""
    if subject.group_installs is not None:
        if subject.uninstall_invocation == ("uninstall",):
            return EffectCaseBuild(_global_uninstall_cases(spec, subject, target))
        return EffectCaseBuild((_group_uninstall_case(spec, subject, target),))
    reinstall = build_reinstall_case(spec, subject, target)
    markdown = [e for e in spec.effects if isinstance(e, MarkdownSectionEffect)]
    skills = [e for e in spec.effects if isinstance(e, SkillEffect)]
    hooks = [e for e in spec.effects if isinstance(e, JsonHooksEffect)]
    entries: list[EffectInstallCase | CaseNonConstruction] = [reinstall]
    entries.extend(_markdown_cases(reinstall, markdown))
    for name, preparation in (
        ("missing-reference", MissingReferencePreparation),
        ("altered-reference", AlteredReferencePreparation),
        ("altered-skill", AlteredSkillPreparation),
        ("preserve-skill-backup", PreserveSkillBackupPreparation),
        ("stale-version", StaleVersionPreparation),
        ("stale-reference", StaleReferencePreparation),
        (StaleReferencesTmpPreparation.kind, StaleReferencesTmpPreparation),
    ):
        entries.append(
            replace(
                reinstall,
                name=name,
                intermediate_preparation=preparation(skills[0].destination),
            )
            if skills
            else CaseNonConstruction(name, "not_applicable", "No skill effect declared")
        )
    for kind in ("missing-json-hook", "altered-json-hook", "duplicate-json-hook"):
        entries.append(
            _json_hook_case(reinstall, hooks[0], kind)
            if hooks
            else CaseNonConstruction(kind, "not_applicable", "No JSON hooks effect declared")
        )
    if reinstall.subject.uninstall_invocation is not None:
        entries.append(_uninstall_case(reinstall))
    return EffectCaseBuild(tuple(entries))


def _markdown_cases(
    reinstall: EffectInstallCase, markdown: list[MarkdownSectionEffect]
) -> tuple[EffectInstallCase | CaseNonConstruction, ...]:
    variants = (
        ("missing-section", "missing-markdown-section", None),
        ("altered-section", "altered-markdown-body", b"\nSandbox altered Markdown section.\n\n"),
    )
    if len(markdown) != 1:
        return tuple(
            CaseNonConstruction(
                name,
                "not_applicable" if not markdown else "unconstructible",
                "No Markdown effect declared"
                if not markdown
                else "The case builder currently supports only one Markdown effect",
            )
            for name, _, _ in variants
        )
    effect = markdown[0]
    preparation = IntermediatePreparation(
        effect.destination,
        effect.marker,
        b"## Personal before\nKeep before.\n\n",
        b"## Personal after\nKeep after.\n\n",
    )
    initial = [dict(item) for item in reinstall.initial_files]
    for item in initial:
        if (item["root"], item["path"]) == (effect.destination.root, effect.destination.path):
            item["content"] = (
                preparation.before
                + effect.marker.encode("utf-8")
                + b"\nReplace this placeholder.\n\n"
                + preparation.after
            ).decode("utf-8")
    return tuple(
        replace(
            reinstall,
            name=name,
            initial_files=initial,
            intermediate_preparation=replace(preparation, kind=kind, body=body),
        )
        for name, kind, body in variants
    )


def _uninstall_case(reinstall: EffectInstallCase) -> EffectInstallCase:
    """Construct targeted project removal from explicit commands and skill data."""
    spec, subject = reinstall.effects, reinstall.subject
    invocation = subject.invocation
    if (
        len(invocation) != 4
        or invocation[:2] != ("install", "--platform")
        or re.fullmatch(r"[a-z][a-z0-9-]*", invocation[2]) is None
        or invocation[3:] != ("--project",)
        or subject.uninstall_invocation != ("uninstall", *invocation[1:])
        or subject.uninstall_user_skill_path is None
        or spec.scope != "project"
        or len(spec.effects) != 1
        or not isinstance(spec.effects[0], SkillEffect)
        or spec.effects[0].destination.root != "project"
    ):
        raise ValueError("Unsupported uninstall composition or subject invocation")
    path = spec.effects[0].destination.path
    user_path = subject.uninstall_user_skill_path
    witnesses: list[InitialFile] = [
        {"root": root, "path": name, "content": content}
        for root, name, content in (
            ("home", user_path + "/SKILL.md", "# User skill witness\n"),
            (
                "home",
                user_path + "/references/sandbox-user-witness.md",
                "User reference witness.\n",
            ),
            ("home", user_path + "/.graphify_version", "user-witness-version\n"),
            ("project", path + "/personal.txt", "Personal project skill content.\n"),
            ("project", path + "/SKILL.md.bak", "Personal previous skill backup.\n"),
            ("project", "graphify-out/personal.txt", "Personal graph output witness.\n"),
        )
    ]
    return replace(
        reinstall,
        name="uninstall",
        operations=["install", "uninstall"],
        initial_files=[*reinstall.initial_files, *witnesses],
    )


def _validated_group_skills(spec: EffectSpec, subject: SubjectContext) -> tuple[SkillEffect, ...]:
    installs = subject.group_installs
    assert installs is not None
    skills = {
        effect.destination: effect for effect in spec.effects if isinstance(effect, SkillEffect)
    }
    destinations = tuple(install.destination for install in installs)
    commands = tuple(install.invocation for install in installs)
    if (
        len(skills) != len(spec.effects)
        or len(destinations) != len(set(destinations))
        or set(destinations) != set(skills)
        or len(commands) != len(set(commands))
        or subject.invocation != commands[0]
        or subject.uninstall_user_skill_path is not None
    ):
        raise ValueError("Unsupported grouped uninstall composition or subject invocation")
    return tuple(skills[destination] for destination in destinations)


def _group_operations(subject: SubjectContext, final: str) -> list[str]:
    assert subject.group_installs is not None
    return [
        "install",
        *(f"install-group-{index}" for index in range(1, len(subject.group_installs))),
        final,
    ]


def _group_uninstall_case(
    spec: EffectSpec, subject: SubjectContext, target: str
) -> EffectInstallCase:
    """Declare arbitrary ordered HOME and project installations with project removal."""
    spec, subject = _validated_inputs(spec, subject)
    skills = _validated_group_skills(spec, subject)
    if (
        spec.scope != "project"
        or subject.purge_invocation is not None
        or subject.home_lock_destinations
        or subject.config_lock_destinations
        or {effect.destination.root for effect in skills} != {"home", "project"}
        or subject.uninstall_invocation != ("uninstall", "--project")
    ):
        raise ValueError("Unsupported grouped uninstall composition or subject invocation")
    witnesses: list[InitialFile] = [
        {
            "root": effect.destination.root,
            "path": effect.destination.path + "/personal.txt",
            "content": "Personal skill content to preserve.\n",
        }
        for effect in skills
    ]
    initial = [*effect_initial_files(spec), *witnesses]
    initial.append(
        _output_witness(initial, "graphify-out/personal.txt", "Personal graph output witness.\n")
    )
    return EffectInstallCase(
        "group-uninstall-project",
        text(target),
        spec.scope,
        spec,
        subject,
        initial,
        _group_operations(subject, "uninstall"),
    )


def _global_uninstall_cases(
    spec: EffectSpec, subject: SubjectContext, target: str
) -> tuple[EffectInstallCase, ...]:
    """Pair ordinary global removal with its explicit output-purging variant."""
    spec, subject = _validated_inputs(spec, subject)
    skills = _validated_group_skills(spec, subject)
    if (
        spec.scope != "user"
        or any(effect.destination.root != "home" for effect in skills)
        or subject.uninstall_invocation != ("uninstall",)
        or subject.purge_invocation != ("uninstall", "--purge")
    ):
        raise ValueError("Unsupported global uninstall composition or subject invocation")
    initial = effect_initial_files(spec, project_skill_witnesses=False)
    initial.extend(
        {
            "root": root,
            "path": effect.destination.path + "/personal.txt",
            "content": "Personal skill content to preserve.\n",
        }
        for effect in skills
        for root in ("home", "project")
    )
    for preferred, content in (
        ("graphify-out/personal.txt", "Graph output witness.\n"),
        ("graphify-out/nested/result.json", '{"graph": "witness"}\n'),
        ("personal-next-to-output.txt", "Personal output sibling.\n"),
    ):
        initial.append(_output_witness(initial, preferred, content))
    ordinary = EffectInstallCase(
        "global-uninstall",
        text(target),
        spec.scope,
        spec,
        subject,
        initial,
        _group_operations(subject, "uninstall"),
    )
    return (
        ordinary,
        replace(
            ordinary, name="global-uninstall-purge", operations=_group_operations(subject, "purge")
        ),
    )
