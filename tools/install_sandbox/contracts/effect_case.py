"""Construct a reinstall case directly from effects and explicit subject rules."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Literal, TypedDict, cast

from tools.install_sandbox.contracts.effects import (
    JSON_BACKUP_SUFFIX,
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
    StaleVersionPreparation,
    preparation_from_data,
)
from tools.install_sandbox.contracts.spec import HookExpectation, fields, relative_path, text


@dataclass(frozen=True)
class CaseKey:
    tool: str
    scope: str
    operation: str
    effect_id: str | None = None
    member: str | None = None

    def __post_init__(self) -> None:
        for value in (self.tool, self.scope, self.operation):
            text(value)
        if self.effect_id is not None:
            text(self.effect_id)
        if self.member is not None:
            text(self.member)
            if self.effect_id is None:
                raise ValueError("Case member requires an effect ID")

    def to_data(self) -> dict[str, object]:
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_data(cls, value: object) -> "CaseKey":
        if not isinstance(value, dict):
            raise ValueError("Expected case key object")
        incoming = cast(dict[str, object], value)
        grouped = "prepare" in incoming or "remove" in incoming
        names = "tool scope operation effect_id member" + (" prepare remove" if grouped else "")
        data = fields(incoming, names)
        key = (
            text(data["tool"]),
            text(data["scope"]),
            text(data["operation"]),
            cast(str | None, data["effect_id"]),
            cast(str | None, data["member"]),
        )
        if grouped:
            return GroupCaseKey(
                *key, prepare=_participants(data["prepare"]), remove=_participants(data["remove"])
            )
        return CaseKey(*key)

    @property
    def storage_id(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_data(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()


def _participants(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("Expected ordered participant arrays")
    return tuple(text(item) for item in cast(list[object], value))


@dataclass(frozen=True, kw_only=True)
class GroupCaseKey(CaseKey):
    prepare: tuple[str, ...]
    remove: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.operation != "group-uninstall" or not self.prepare or not self.remove:
            raise ValueError("Ordered participants require a group-uninstall key")
        if len(set(self.prepare)) != len(self.prepare) or len(set(self.remove)) != len(self.remove):
            raise ValueError("Duplicate ordered group participants")
        if not set(self.remove) <= set(self.prepare):
            raise ValueError("Removed participants must have been prepared")
        if any(len(p.split(":")) != 2 or not all(p.split(":")) for p in self.prepare):
            raise ValueError("Expected participant tool:scope")


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
class StepInvocation:
    action: str
    participants: tuple[str, ...]
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action not in {"install", "uninstall"} or not self.participants or not self.argv:
            raise ValueError("Expected an explicit step invocation")
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("Duplicate step participant")
        for item in (*self.participants, *self.argv):
            if "\x00" in text(item):
                raise ValueError("Invalid step argument")

    def to_data(self) -> dict[str, object]:
        return {
            "action": self.action,
            "participants": list(self.participants),
            "argv": list(self.argv),
        }

    @classmethod
    def from_data(cls, value: object) -> "StepInvocation":
        data = fields(value, "action participants argv")
        if not isinstance(data["participants"], list) or not isinstance(data["argv"], list):
            raise ValueError("Expected step argument lists")
        return cls(
            text(data["action"]),
            tuple(text(x) for x in cast(list[object], data["participants"])),
            tuple(text(x) for x in cast(list[object], data["argv"])),
        )


@dataclass(frozen=True)
class SubjectContext:
    identity: str
    invocation: tuple[str, ...]
    version_source: str
    rules: EffectRules
    package_root: str | None = None
    revision: str | None = None
    invocations: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict[str, tuple[str, ...]]()
    )

    removals: tuple["StepInvocation", ...] = ()

    def bind_participant(self, tool: str, scope: str) -> "SubjectContext":
        argv = self.invocations.get(f"{tool}:{scope}")
        if argv is None and scope == "project":
            argv = self.invocation
        if not argv:
            raise ValueError(f"Missing installation invocation for {tool}:{scope}")
        return replace(self, invocation=argv)

    @classmethod
    def from_data(cls, value: object) -> "SubjectContext":
        data = _context_fields(value)
        if not isinstance(data["removals"], list):
            raise ValueError("Expected grouped removal invocations")
        raw = data["invocation"]
        if not isinstance(raw, list):
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
            _invocations(data["invocations"]),
            tuple(StepInvocation.from_data(item) for item in cast(list[object], data["removals"])),
        )


def _invocations(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise ValueError("Expected participant invocations")
    result: dict[str, tuple[str, ...]] = {}
    for key, raw in cast(dict[str, object], value).items():
        if ":" not in key or not isinstance(raw, list) or not raw:
            raise ValueError("Expected participant invocation arguments")
        args = tuple(text(arg) for arg in cast(list[object], raw))
        if any("\x00" in arg for arg in args):
            raise ValueError("Invalid invocation argument")
        result[text(key)] = args
    return result


def _context_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a subject context object")
    incoming = cast(dict[str, object], value)
    data = fields(
        {
            "package_root": None,
            "revision": None,
            "invocation": [],
            "invocations": {},
            "removals": [],
            **incoming,
        },
        "identity invocation version_source rules package_root revision invocations removals",
    )
    root, revision = data["package_root"], data["revision"]
    if root is not None:
        relative_path(root)
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError("Package preparation requires an exact subject commit SHA")
    elif revision is not None:
        raise ValueError("Subject revision requires a package root")
    return data


def _validate_hook_rules(effect: JsonHooksEffect, rules: EffectRules) -> None:
    if rules.json_backup != JSON_BACKUP_SUFFIX or rules.json_registry is not False:
        raise ValueError("Unsupported or missing JSON hooks reinstall rule")
    if any(
        "timeout" in hook.content and type(hook.content["timeout"]) is not int
        for hook in effect.hooks
    ):
        raise ValueError("Hook timeout must be an integer when declared")


def validate_effect_rules(spec: EffectSpec, subject: SubjectContext) -> None:
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


def _json_witness(spec: EffectSpec, command: str, timeout: int) -> dict[str, object]:
    """Choose a personal command disjoint from every declared managed hook."""
    reserved = {
        hook.content.get("command")
        for effect in spec.effects
        if isinstance(effect, JsonHooksEffect)
        for hook in effect.hooks
    }
    candidate = command
    suffix = 0
    while candidate in reserved:
        suffix += 1
        candidate = f"{command}.sandbox-{suffix}"
    return {"type": "command", "command": candidate, "timeout": timeout}


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
                                        _json_witness(spec, "python personal_graphify_audit.py", 17)
                                    ],
                                }
                            ],
                            "PostToolUse": [
                                {
                                    "matcher": "Read",
                                    "hooks": [
                                        _json_witness(spec, "python personal_after_read.py", 9)
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


def seeded_json_hook_group(
    effect: JsonHooksEffect, member: HookExpectation, spec: EffectSpec
) -> dict[str, object]:
    """Independent cohabitation witness for the selected declared hook."""
    if member not in effect.hooks:
        raise ValueError("Selected hook does not belong to the effect")
    hook = member
    return {
        "matcher": hook.matcher,
        "sandbox_personal": "preserve",
        "hooks": [
            dict(hook.content),
            _json_witness(spec, "python personal_graphify_audit.py", 17),
        ],
    }


def _json_hook_case(
    reinstall: "EffectInstallCase", effect: JsonHooksEffect, hook: HookExpectation
) -> "EffectInstallCase":
    neighbor: dict[str, object] = {
        "matcher": "SandboxPersonalNeighbor",
        "sandbox_neighbor": True,
        "hooks": [_json_witness(reinstall.effects, "python personal_neighbor.py", 23)],
    }
    same_matcher = {
        "matcher": hook.matcher,
        "sandbox_personal": "ordered",
        "hooks": [
            _json_witness(reinstall.effects, "python personal_before.py", 19),
            _json_witness(reinstall.effects, "python personal_after.py", 29),
        ],
    }
    groups = [seeded_json_hook_group(effect, hook, reinstall.effects), same_matcher, neighbor]
    settings = {
        "theme": "dark",
        "metadata": {"owner": "personal"},
        "hooks": {hook.event: groups},
    }
    initial = [dict(item) for item in reinstall.initial_files]
    for item in initial:
        if (item["root"], item["path"]) == (effect.destination.root, effect.destination.path):
            item["content"] = json.dumps(settings, indent=2) + "\n"
    return replace(
        reinstall,
        name="missing-json-hook",
        key=CaseKey(
            reinstall.key.tool, reinstall.scope, "missing-json-hook", effect.effect_id, hook.id
        ),
        initial_files=initial,
        intermediate_preparation=JsonHookPreparation(
            effect.destination, "missing-json-hook", effect.effect_id, hook.id
        ),
    )


@dataclass(frozen=True)
class EffectInstallCase:
    name: str
    key: CaseKey
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
        | None
    ) = None

    participants: tuple[tuple[str, EffectSpec], ...] = ()
    plan: tuple[StepInvocation, ...] = ()

    @property
    def group(self):
        if not self.participants:
            return None
        from tools.install_sandbox.contracts.group_case import GroupPlan

        if not isinstance(self.key, GroupCaseKey):
            raise ValueError("Group participants require a grouped key")
        return GroupPlan(dict(self.participants), self.key.prepare, self.key.remove)

    @property
    def steps(self) -> tuple[StepInvocation, ...]:
        return self.plan or tuple(
            StepInvocation(op, (f"{self.key.tool}:{self.scope}",), self.subject.invocation)
            for op in self.operations
        )

    def to_json(self) -> str:
        data = asdict(self)
        data["key"] = self.key.to_data()
        data["format"] = "explicit-expectations-v11"
        data["participants"] = [
            {"participant": name, "effects": spec.to_data()} for name, spec in self.participants
        ]
        data["plan"] = [step.to_data() for step in self.steps]
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
            "format name key target scope effects subject initial_files operations "
            "intermediate_preparation participants plan",
        )
        if data["format"] != "explicit-expectations-v11":
            raise ValueError("Unsupported effects case format or operation")
        if not isinstance(data["participants"], list) or not isinstance(data["plan"], list):
            raise ValueError("Expected participant and ordered step arrays")
        if data["participants"]:
            from tools.install_sandbox.contracts.group_case import group_from_data

            return group_from_data(data)
        builds = build_effect_cases(
            EffectSpec.from_data(data["effects"]),
            SubjectContext.from_data(data["subject"]),
            CaseKey.from_data(data["key"]).tool,
        )
        matches = [
            case
            for case in builds.cases
            if case.key == CaseKey.from_data(data["key"]) and case.name == data["name"]
        ]
        if not matches:
            raise ValueError("Unsupported effects case")
        case = matches[0]
        preparation = data["intermediate_preparation"]
        parsed = None if preparation is None else preparation_from_data(preparation)
        if (
            tuple(StepInvocation.from_data(step) for step in cast(list[object], data["plan"]))
            != case.steps
            or parsed != case.intermediate_preparation
            or data["target"] != case.target
            or SubjectContext.from_data(data["subject"]) != case.subject
            or data["scope"] != case.scope
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
    subject = subject.bind_participant(target, spec.scope)
    validate_effect_rules(spec, subject)
    return EffectInstallCase(
        "reinstall",
        CaseKey(text(target), spec.scope, "reinstall"),
        subject.identity,
        spec.scope,
        spec,
        subject,
        effect_initial_files(spec),
        ["install", "install"],
    )


@dataclass(frozen=True)
class CaseNonConstruction:
    key: CaseKey
    classification: Literal["not_applicable", "unconstructible"]
    reason: str

    @property
    def name(self) -> str:
        return self.key.operation

    def __post_init__(self) -> None:
        text(self.reason)
        if self.classification not in {"not_applicable", "unconstructible"}:
            raise ValueError("Invalid case non-construction classification")


@dataclass(frozen=True)
class EffectCaseBuild:
    entries: tuple[EffectInstallCase | CaseNonConstruction, ...]

    def __post_init__(self) -> None:
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate campaign case key")

    @property
    def cases(self) -> tuple[EffectInstallCase, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, EffectInstallCase))

    @property
    def decisions(self) -> tuple[CaseNonConstruction, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, CaseNonConstruction))


def build_effect_cases(
    spec: EffectSpec, subject: SubjectContext, target: str = "controlled"
) -> EffectCaseBuild:
    """Enumerate participant obligations before binding executable commands."""
    spec = EffectSpec.from_data(spec.to_data())
    subject = SubjectContext.from_data(json.loads(json.dumps(asdict(subject))))
    entries: list[EffectInstallCase | CaseNonConstruction] = []
    missing: str | None = None
    try:
        bound = subject.bind_participant(target, spec.scope)
    except ValueError as error:
        missing = str(error)
        bound = subject
    executable_subject = bound
    multi_skill = sum(isinstance(e, SkillEffect) for e in spec.effects) > 1
    for effect in spec.effects:
        validate_effect_rules(EffectSpec((effect,), spec.scope), executable_subject)
    reinstall = EffectInstallCase(
        "reinstall",
        CaseKey(target, spec.scope, "reinstall"),
        subject.identity,
        spec.scope,
        spec,
        executable_subject,
        effect_initial_files(spec),
        ["install", "install"],
    )
    entries.append(reinstall)
    markdown = [e for e in spec.effects if isinstance(e, MarkdownSectionEffect)]
    entries.extend(_markdown_cases(reinstall, markdown))
    skills = [e for e in spec.effects if isinstance(e, SkillEffect)]
    for name, preparation in (
        ("missing-reference", MissingReferencePreparation),
        ("altered-reference", AlteredReferencePreparation),
        ("altered-skill", AlteredSkillPreparation),
        ("preserve-skill-backup", PreserveSkillBackupPreparation),
        ("stale-version", StaleVersionPreparation),
        ("stale-reference", StaleReferencePreparation),
    ):
        if skills:
            entries.extend(
                replace(
                    reinstall,
                    name=name,
                    key=CaseKey(target, spec.scope, name, e.effect_id),
                    intermediate_preparation=preparation(e.destination),
                )
                for e in skills
            )
        else:
            entries.append(
                CaseNonConstruction(
                    CaseKey(target, spec.scope, name), "not_applicable", "No skill effect declared"
                )
            )
    entries.extend(_json_cases(reinstall))
    reason = missing or (
        "Multiple skill effects require unavailable lock observation capability"
        if multi_skill
        else None
    )
    if reason:
        entries = [
            CaseNonConstruction(e.key, "unconstructible", reason)
            if isinstance(e, EffectInstallCase)
            else e
            for e in entries
        ]
    return EffectCaseBuild(tuple(entries))


def _json_cases(
    reinstall: EffectInstallCase,
) -> tuple[EffectInstallCase | CaseNonConstruction, ...]:
    cases = tuple(
        _json_hook_case(reinstall, effect, hook)
        for effect in reinstall.effects.effects
        if isinstance(effect, JsonHooksEffect)
        for hook in effect.hooks
    )
    return cases or (
        CaseNonConstruction(
            CaseKey(reinstall.key.tool, reinstall.scope, "missing-json-hook"),
            "not_applicable",
            "No JSON hooks effect declared",
        ),
    )


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
                CaseKey(reinstall.key.tool, reinstall.scope, name),
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
            key=CaseKey(reinstall.key.tool, reinstall.scope, name, effect.effect_id),
            initial_files=initial,
            intermediate_preparation=replace(preparation, kind=kind, body=body),
        )
        for name, kind, body in variants
    )
