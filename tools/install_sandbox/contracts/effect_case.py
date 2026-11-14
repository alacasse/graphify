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
        if self.operation == "group-uninstall":
            raise ValueError("group-uninstall has been retired")
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
        data = fields(incoming, "tool scope operation effect_id member")
        key = (
            text(data["tool"]),
            text(data["scope"]),
            text(data["operation"]),
            cast(str | None, data["effect_id"]),
            cast(str | None, data["member"]),
        )
        return CaseKey(*key)

    @property
    def storage_id(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_data(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()


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
    skill_lock: str
    json_backup: str
    skill_backup: str
    json_registry: bool

    @classmethod
    def from_data(cls, value: object) -> "EffectRules":
        data = fields(value, "skill_lock json_backup skill_backup json_registry")
        if type(data["json_registry"]) is not bool:
            raise ValueError("Expected explicit registry rule")
        return cls(
            text(data["skill_lock"]),
            text(data["json_backup"]),
            text(data["skill_backup"]),
            data["json_registry"],
        )


@dataclass(frozen=True)
class StepInvocation:
    action: str
    participant: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action not in ("install", "uninstall") or not self.argv:
            raise ValueError("Expected an explicit step invocation")
        for item in (self.participant, *self.argv):
            if "\x00" in text(item):
                raise ValueError("Invalid step argument")

    def to_data(self) -> dict[str, object]:
        return {
            "action": self.action,
            "participants": [self.participant],
            "argv": list(self.argv),
        }


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

    # An ordinary v11 archive can retain unused removal metadata from a shared context.
    removals: tuple[dict[str, object], ...] = ()

    prerequisites: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    uninstall_invocations: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict[str, tuple[str, ...]]()
    )

    def to_data(self) -> dict[str, object]:
        data = asdict(self)
        for name in ("prerequisites", "uninstall_invocations"):
            if not data[name]:
                data.pop(name)
        timeout = data.pop("_archived_timeout", None)
        if timeout is not None:
            data["rules"] = {"hook_timeout": timeout, **asdict(self.rules)}
        return json.loads(json.dumps(data))

    @classmethod
    def from_archive_data(cls, value: object) -> "SubjectContext":
        if not isinstance(value, dict):
            raise ValueError("Expected a subject context object")
        data = dict(cast(dict[str, object], value))
        raw = data.get("rules")
        if not isinstance(raw, dict) or "hook_timeout" not in raw:
            return cls.from_data(data)
        rules = dict(cast(dict[str, object], raw))
        timeout = rules.pop("hook_timeout")
        if type(timeout) is not int:
            raise ValueError("Expected historical integer hook timeout")
        data["rules"] = rules
        context = _ArchivedSubjectContext.from_data(data)
        return replace(cast(_ArchivedSubjectContext, context), _archived_timeout=timeout)

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
            _archived_removals(data["removals"]),
            _prerequisites(data["prerequisites"]),
            _invocations(data["uninstall_invocations"]),
        )


@dataclass(frozen=True)
class _ArchivedSubjectContext(SubjectContext):
    """Reader-only v11 wire metadata; absent from current subject contexts."""

    _archived_timeout: int = field(default=0, repr=False)


def _archived_removals(value: object) -> tuple[dict[str, object], ...]:
    """Retain v11 context data in its original wire order for ordinary campaign replay."""
    if not isinstance(value, list):
        raise ValueError("Expected removal metadata array")
    records: list[dict[str, object]] = []
    for record in cast(list[object], value):
        data = fields(record, "action participants argv")
        action, participants, argv = data["action"], data["participants"], data["argv"]
        if (
            action not in ("install", "uninstall")
            or not isinstance(participants, list)
            or not isinstance(argv, list)
        ):
            raise ValueError("Invalid removal metadata")
        names = [text(name) for name in cast(list[object], participants)]
        args = [text(arg) for arg in cast(list[object], argv)]
        if (
            not names
            or not args
            or len(set(names)) != len(names)
            or any("\x00" in word for word in (*names, *args))
        ):
            raise ValueError("Invalid removal metadata")
        records.append({"action": action, "participants": names, "argv": args})
    return tuple(records)


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


def _prerequisites(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Expected participant prerequisites")
    result = {text(k): text(v) for k, v in cast(dict[str, object], value).items()}
    if any(":" not in k or ":" not in v or k == v for k, v in result.items()):
        raise ValueError("Expected distinct prerequisite participants")
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
            "prerequisites": {},
            "uninstall_invocations": {},
            **incoming,
        },
        "identity invocation version_source rules package_root revision invocations removals "
        "prerequisites uninstall_invocations",
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

    prerequisite_effects: EffectSpec | None = None
    prerequisite_participant: str | None = None

    @property
    def repair_after_index(self) -> int:
        return int(self.prerequisite_effects is not None)

    @property
    def step_effects(self) -> tuple[EffectSpec, ...]:
        prefix = () if self.prerequisite_effects is None else (self.prerequisite_effects,)
        return prefix + tuple(self.effects for _ in self.operations)

    @property
    def steps(self) -> tuple[StepInvocation, ...]:
        prefix = ()
        if self.prerequisite_participant is not None:
            prefix = (
                StepInvocation(
                    "install",
                    self.prerequisite_participant,
                    self.subject.invocations[self.prerequisite_participant],
                ),
            )
        participant = f"{self.key.tool}:{self.scope}"
        return prefix + tuple(
            StepInvocation(
                op,
                participant,
                self.subject.invocation
                if op == "install"
                else self.subject.uninstall_invocations[participant],
            )
            for op in self.operations
        )

    def to_json(self) -> str:
        data = asdict(self)
        data["subject"] = self.subject.to_data()
        if self.prerequisite_effects is None:
            data.pop("prerequisite_effects")
            data.pop("prerequisite_participant")
        else:
            data["prerequisite_effects"] = self.prerequisite_effects.to_data()
        # Campaign replay checks the original v11 case bytes, including field order.
        data["key"] = self.key.to_data()
        data["participants"] = []
        data["plan"] = [step.to_data() for step in self.steps]
        data["format"] = (
            "explicit-expectations-v11"
            if isinstance(self.subject, _ArchivedSubjectContext)
            else (
                "explicit-expectations-v13"
                if self.subject.prerequisites or self.subject.uninstall_invocations
                else "explicit-expectations-v12"
            )
        )
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
        data = _case_transport_data(payload)
        subject = _case_subject(data)
        builds = build_effect_cases(
            EffectSpec.from_data(data["effects"]),
            subject,
            CaseKey.from_data(data["key"]).tool,
            prerequisite_effects=(
                None
                if data["prerequisite_effects"] is None
                else EffectSpec.from_data(data["prerequisite_effects"])
            ),
            prerequisite_participant=cast(str | None, data["prerequisite_participant"]),
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
            data["prerequisite_participant"] != case.prerequisite_participant
            or data["prerequisite_effects"]
            != (None if case.prerequisite_effects is None else case.prerequisite_effects.to_data())
            or data["plan"] != [step.to_data() for step in case.steps]
            or parsed != case.intermediate_preparation
            or data["target"] != case.target
            or subject != case.subject
            or data["scope"] != case.scope
            or data["operations"] != case.operations
            or data["initial_files"] != case.initial_files
        ):
            raise ValueError("Effects case preparation or operations do not match definition")
        return case


def _case_transport_data(payload: str) -> dict[str, object]:
    incoming = json.loads(payload, object_pairs_hook=unique_object)
    if not isinstance(incoming, dict):
        raise ValueError("Expected effects case object")
    raw = cast(dict[str, object], incoming)
    version = raw.get("format")
    if version not in (
        "explicit-expectations-v11",
        "explicit-expectations-v12",
        "explicit-expectations-v13",
    ):
        raise ValueError("Unsupported effects case format or operation")
    if version != "explicit-expectations-v13" and any(
        name in raw for name in ("prerequisite_effects", "prerequisite_participant")
    ):
        raise ValueError("Historical case cannot declare prerequisites")
    data = fields(
        {"prerequisite_effects": None, "prerequisite_participant": None, **raw},
        "prerequisite_effects prerequisite_participant format name key target scope effects "
        "subject initial_files operations intermediate_preparation participants plan",
    )
    if not isinstance(data["participants"], list) or not isinstance(data["plan"], list):
        raise ValueError("Expected participant and ordered step arrays")
    if data["participants"]:
        raise ValueError("Grouped case transports have been retired")
    return data


def _case_subject(data: dict[str, object]) -> SubjectContext:
    reader = (
        SubjectContext.from_archive_data
        if data["format"] == "explicit-expectations-v11"
        else SubjectContext.from_data
    )
    subject = reader(data["subject"])
    version = data["format"]
    if version != "explicit-expectations-v13" and (
        subject.prerequisites or subject.uninstall_invocations
    ):
        raise ValueError("Historical case cannot declare execution prerequisites")
    if data["format"] == "explicit-expectations-v11" and not isinstance(
        subject, _ArchivedSubjectContext
    ):
        raise ValueError("Historical v11 case requires its explicit timeout rule")
    return subject


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
    spec: EffectSpec,
    subject: SubjectContext,
    target: str = "controlled",
    *,
    prerequisite_effects: EffectSpec | None = None,
    prerequisite_participant: str | None = None,
) -> EffectCaseBuild:
    """Enumerate participant obligations before binding executable commands."""
    spec = EffectSpec.from_data(spec.to_data())
    subject = SubjectContext.from_archive_data(subject.to_data())
    entries: list[EffectInstallCase | CaseNonConstruction] = []
    missing: str | None = None
    try:
        bound = subject.bind_participant(target, spec.scope)
    except ValueError as error:
        missing = str(error)
        bound = subject
    participant = f"{target}:{spec.scope}"
    expected_prerequisite = subject.prerequisites.get(participant)
    uninstall = participant in subject.uninstall_invocations
    prerequisite_error = _prerequisite_error(
        spec, subject, target, prerequisite_effects, prerequisite_participant
    )
    if expected_prerequisite:
        missing = missing or prerequisite_error
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
        prerequisite_effects=prerequisite_effects if expected_prerequisite else None,
        prerequisite_participant=prerequisite_participant if expected_prerequisite else None,
    )
    entries.append(reinstall)
    markdown = [e for e in spec.effects if isinstance(e, MarkdownSectionEffect)]
    entries.extend(_markdown_cases(reinstall, markdown))
    entries.extend(_skill_cases(reinstall))
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
    if uninstall:
        entries.append(
            _uninstall_case(
                reinstall,
                prerequisite_effects,
                prerequisite_participant,
                prerequisite_error or missing,
            )
        )
    return EffectCaseBuild(tuple(entries))


def _skill_cases(
    reinstall: EffectInstallCase,
) -> tuple[EffectInstallCase | CaseNonConstruction, ...]:
    entries: list[EffectInstallCase | CaseNonConstruction] = []
    skills = [e for e in reinstall.effects.effects if isinstance(e, SkillEffect)]
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
                    key=CaseKey(reinstall.key.tool, reinstall.scope, name, e.effect_id),
                    intermediate_preparation=preparation(e.destination),
                )
                for e in skills
            )
        else:
            entries.append(
                CaseNonConstruction(
                    CaseKey(reinstall.key.tool, reinstall.scope, name),
                    "not_applicable",
                    "No skill effect declared",
                )
            )
    return tuple(entries)


def _prerequisite_error(
    spec: EffectSpec,
    subject: SubjectContext,
    target: str,
    effects: EffectSpec | None,
    participant: str | None,
) -> str | None:
    primary = f"{target}:{spec.scope}"
    expected = subject.prerequisites.get(primary)
    if primary in subject.uninstall_invocations and expected is None:
        expected = f"{target}:user"
    if expected is None:
        return None
    if participant is None or participant != expected or expected.split(":")[0] != target:
        return "Missing or inconsistent prerequisite participant"
    if effects is None or effects.scope != participant.rsplit(":", 1)[-1]:
        return "Prerequisite participant and effects disagree"
    if participant not in subject.invocations:
        return f"Missing installation invocation for {participant}"
    if (
        len(spec.effects) != 1
        or not isinstance(spec.effects[0], SkillEffect)
        or len(effects.effects) != 1
        or not isinstance(effects.effects[0], SkillEffect)
    ):
        return "Prerequisites require two single-skill scopes"
    left, right = spec.effects[0].destination, effects.effects[0].destination
    if left.root == right.root and (
        PurePosixPath(left.path) == PurePosixPath(right.path)
        or PurePosixPath(left.path) in PurePosixPath(right.path).parents
        or PurePosixPath(right.path) in PurePosixPath(left.path).parents
    ):
        return "Prerequisite effects overlap target effects"
    return None


def _uninstall_case(
    reinstall: EffectInstallCase,
    effects: EffectSpec | None,
    participant: str | None,
    error: str | None,
) -> EffectInstallCase | CaseNonConstruction:
    key = CaseKey(reinstall.key.tool, reinstall.scope, "uninstall")
    if reinstall.scope != "project" or effects is None or effects.scope != "user":
        error = error or "Uninstall requires project and user single-skill scopes"
    if error or effects is None or participant is None:
        return CaseNonConstruction(
            key, "unconstructible", error or "Missing uninstall prerequisite"
        )
    witnesses: list[InitialFile] = [item.copy() for item in reinstall.initial_files]
    for specification in (reinstall.effects, effects):
        for effect in specification.effects:
            destination = effect.destination
            paths = (
                destination.path + "/personal.txt",
                str(PurePosixPath(destination.path).parent / "personal/SKILL.md"),
            )
            for path in paths:
                witnesses.append(
                    {
                        "root": destination.root,
                        "path": path,
                        "content": "Personal document to preserve.\n",
                    }
                )
    destination = reinstall.effects.effects[0].destination
    witnesses.extend(
        [
            {
                "root": "project",
                "path": "graphify-out/personal.txt",
                "content": "Personal document to preserve.\n",
            },
            {
                "root": destination.root,
                "path": destination.path + "/SKILL.md.bak",
                "content": "Personal document to preserve.\n",
            },
        ]
    )
    return replace(
        reinstall,
        name="uninstall",
        key=key,
        initial_files=witnesses,
        operations=["install", "uninstall"],
        prerequisite_effects=effects,
        prerequisite_participant=participant,
    )


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
