"""Verify composed native effects against retained sources and personal witnesses."""

from email.parser import BytesParser
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.container import verifier as checks
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import (
    Effect,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.results import ObservationObstacle, VerificationResult
from tools.install_sandbox.contracts.spec import HookExpectation


def _result(*snapshots: FilesystemSnapshot) -> VerificationResult:
    result = VerificationResult(
        obstacles=[ObservationObstacle(**o) for snapshot in snapshots for o in snapshot.obstacles]
    )
    for snapshot in snapshots:
        _complete_observation(snapshot, result)
    for snapshot in snapshots[1:]:
        for root in ("home", "project"):
            entry = snapshot.entry(root, ".")
            if entry is None or entry["kind"] != "directory":
                _obstacle(result, root, ".", "Complete observed root unavailable")
    return result


def _complete_observation(snapshot: FilesystemSnapshot, result: VerificationResult) -> None:
    for entry in snapshot.entries:
        root, path = entry["root"], entry["path"]
        if entry["kind"] == "directory":
            if not entry.get("listing_complete"):
                _obstacle(result, root, path, "Complete directory inventory unavailable")
        elif entry["kind"] == "file":
            if (root, path) not in snapshot.contents:
                _obstacle(result, root, path, "Retained file bytes unavailable")
        else:
            _obstacle(result, root, path, "Unsupported observed entry")


def _obstacle(result: VerificationResult, root: str, path: str, reason: str) -> None:
    result.obstacles.append(
        {
            "operation": "verify_effect",
            "root": root,
            "path": path,
            "reason": reason,
        }
    )


def _source_inventory(
    effect: SkillEffect,
    expected: FilesystemSnapshot,
    result: VerificationResult,
) -> bool:
    entry = expected.entry("subject", effect.references)
    if entry is None or entry["kind"] != "directory" or not entry.get("listing_complete"):
        _obstacle(result, "subject", effect.references, "Complete source references unavailable")
        return False
    for source in expected.entries:
        if source["path"].startswith(effect.references + "/"):
            if source["kind"] == "file":
                checks.expected_file(expected, source["path"], result)
            elif source["kind"] != "directory" or not source.get("listing_complete"):
                _obstacle(result, "subject", source["path"], "Incomplete reference observation")
    return True


def _version(
    case: EffectInstallCase,
    expected: FilesystemSnapshot,
    result: VerificationResult,
) -> bytes | None:
    source = checks.expected_file(expected, case.subject.version_source, result)
    if source is None:
        return None
    versions = BytesParser().parsebytes(source).get_all("Version", [])
    if len(versions) != 1 or not versions[0].strip():
        _obstacle(result, "subject", case.subject.version_source, "Expected one metadata Version")
        return None
    return versions[0].strip().encode("utf-8")


def _skill(
    case: EffectInstallCase,
    effect: SkillEffect,
    expected: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    root, path = effect.destination.root, effect.destination.path
    source = checks.expected_file(expected, effect.source, result)
    if source is not None:
        checks.compare_bytes(after, path + "/SKILL.md", source, result, root)
    if _source_inventory(effect, expected, result):
        checks.reference_files(
            expected, after, effect.references, path + "/references", result, root
        )
    version = _version(case, expected, result)
    if version is not None:
        checks.compare_bytes(after, path + "/.graphify_version", version, result, root)
    checks.require_absent(after, path + "/SKILL.md" + case.subject.rules.skill_backup, result, root)


def _managed_hook(
    hooks: tuple[HookExpectation, ...],
    event: str,
    group: dict[str, object],
    content: dict[str, object],
) -> bool:
    return any(
        hook.event == event
        and hook.matcher == group.get("matcher")
        and all(
            key in content and checks.json_equal(content[key], value)
            for key, value in hook.content.items()
        )
        for hook in hooks
    )


def _personal_groups(
    hooks: tuple[HookExpectation, ...], event: str, groups: list[object]
) -> list[object]:
    result: list[object] = []
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Hook groups must be objects")
        group = cast(dict[str, object], raw)
        contents = checks.group_hooks(group, event)
        personal = [
            content for _, content in contents if not _managed_hook(hooks, event, group, content)
        ]
        removed = len(personal) != len(contents)
        if removed and not personal and set(group) == {"matcher", "hooks"}:
            continue
        result.append({**group, "hooks": personal} if removed else group)
    return result


def _personal_json(
    hooks: tuple[HookExpectation, ...], document: dict[str, object]
) -> dict[str, object]:
    result = dict(document)
    raw = document.get("hooks")
    if raw is None:
        return result
    if not isinstance(raw, dict):
        raise ValueError("hooks must be an object")
    events: dict[str, object] = {}
    for event, groups in cast(dict[str, object], raw).items():
        if not isinstance(groups, list):
            raise ValueError("Hook events must contain group lists")
        personal = _personal_groups(hooks, event, cast(list[object], groups))
        if personal or not groups:
            events[event] = personal
    if events or not raw:
        result["hooks"] = events
    else:
        result.pop("hooks", None)
    return result


def _json(effect: JsonHooksEffect, before: bytes, after: bytes, result: VerificationResult) -> None:
    root, path = effect.destination.root, effect.destination.path
    try:
        initial, installed = checks.read_json(before), checks.read_json(after)
        for hook in effect.hooks:
            count = len(
                checks.hook_positions(
                    installed, hook.event, hook.matcher, hook.content, exact=False
                )
            )
            if count != 1:
                checks.mismatch(result, "hook_count", root, path, "one conforming hook", str(count))
        if not checks.json_equal(
            _personal_json(effect.hooks, initial), _personal_json(effect.hooks, installed)
        ):
            checks.mismatch(
                result,
                "user_content_lost",
                root,
                path,
                "personal JSON preserved",
                "personal JSON changed",
            )
    except (ValueError, UnicodeError):
        checks.mismatch(result, "invalid_json", root, path, "valid JSON hooks", "invalid JSON")


def _shared(
    effect: MarkdownSectionEffect | JsonHooksEffect,
    expected: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    root, path = effect.destination.root, effect.destination.path
    initial = checks.file(before, path, result, root)
    installed = checks.file(after, path, result, root)
    if initial is None or installed is None:
        return
    if isinstance(effect, JsonHooksEffect):
        _json(effect, initial, installed, result)
        return
    source = checks.expected_file(expected, effect.source, result)
    if source is not None:
        checks.verify_markdown_section(
            source, initial, installed, result, root=root, path=path, marker=effect.marker
        )


def _json_auxiliary(
    case: EffectInstallCase,
    effect: JsonHooksEffect,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    root, path = effect.destination.root, effect.destination.path
    backup = path + case.subject.rules.json_backup
    origin = backup if before.entry(root, backup) is not None else path
    original = checks.file(before, origin, result, root)
    if original is not None:
        checks.compare_bytes(after, backup, original, result, root)
    for suffix in (".bak", ".graphify-state.json", ".graphify.lock", ".graphify-journal.json"):
        checks.require_absent(after, path + suffix, result, root)


def _allowed(case: EffectInstallCase, expected: FilesystemSnapshot) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for effect in case.effects.effects:
        root, path = effect.destination.root, effect.destination.path
        if isinstance(effect, SkillEffect):
            paths = [path, path + "/SKILL.md", path + "/.graphify_version"]
            paths.extend(
                path + "/references" + entry["path"][len(effect.references) :]
                for entry in expected.entries
                if entry["path"] == effect.references
                or entry["path"].startswith(effect.references + "/")
            )
        else:
            paths = [path]
            if isinstance(effect, JsonHooksEffect):
                paths.append(path + case.subject.rules.json_backup)
        for target in paths:
            allowed.add((root, target))
            allowed.update((root, str(parent)) for parent in PurePosixPath(target).parents)
    if expected.skill_lock is not None:
        allowed.add(("home", expected.skill_lock))
        allowed.update(("home", str(p)) for p in PurePosixPath(expected.skill_lock).parents)
    return allowed


def _preservation(
    case: EffectInstallCase,
    expected: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    allowed = _allowed(case, expected)
    for root, path in sorted({(e["root"], e["path"]) for s in (before, after) for e in s.entries}):
        if (root, path) in allowed:
            left, right = before.entry(root, path), after.entry(root, path)
            if left is None:
                continue
            if right is not None and left["kind"] == right["kind"]:
                continue
        checks.preserved_entry(before, after, root, path, result)


def _reinstall(
    case: EffectInstallCase,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    result: VerificationResult,
) -> None:
    # Witness bytes distinguish the first installation from the dependent reinstall.
    initial = {(f["root"], f["path"]): f["content"].encode("utf-8") for f in case.initial_files}
    skill_present = any(
        isinstance(effect, SkillEffect)
        and before.entry(effect.destination.root, effect.destination.path + "/SKILL.md") is not None
        for effect in case.effects.effects
    )
    if not skill_present and all(
        before.contents.get(key) == content for key, content in initial.items()
    ):
        return
    for root, path in sorted({(e["root"], e["path"]) for s in (before, after) for e in s.entries}):
        checks.preserved_entry(before, after, root, path, result)


class EffectVerifier:
    """Check effects directly without reconstructing a legacy installation spec."""

    def verify_initial(
        self, case: EffectInstallCase, expected: FilesystemSnapshot, before: FilesystemSnapshot
    ) -> VerificationResult:
        result = _result(expected, before)
        for initial in case.initial_files:
            checks.compare_bytes(
                before, initial["path"], initial["content"].encode("utf-8"), result, initial["root"]
            )
        for effect in case.effects.effects:
            self._initial_effect(case, effect, expected, before, result)
        result.complete = not result.obstacles
        return result

    def _initial_effect(
        self,
        case: EffectInstallCase,
        effect: Effect,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        result: VerificationResult,
    ) -> None:
        root, path = effect.destination.root, effect.destination.path
        if isinstance(effect, SkillEffect):
            checks.expected_file(expected, effect.source, result)
            _source_inventory(effect, expected, result)
            _version(case, expected, result)
            checks.require_absent(before, path, result, root)
            checks.require_absent(
                before, path + "/SKILL.md" + case.subject.rules.skill_backup, result, root
            )
            if expected.skill_lock is None:
                _obstacle(result, "home", ".", "Independent lock expectation unavailable")
            else:
                checks.require_absent(before, expected.skill_lock, result, "home")
        elif isinstance(effect, MarkdownSectionEffect):
            checks.expected_file(expected, effect.source, result)
        else:
            checks.require_absent(before, path + case.subject.rules.json_backup, result, root)

    def verify(
        self,
        case: EffectInstallCase,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        after: FilesystemSnapshot,
    ) -> VerificationResult:
        result = _result(expected, before, after)
        for effect in case.effects.effects:
            if isinstance(effect, SkillEffect):
                _skill(case, effect, expected, after, result)
            else:
                _shared(effect, expected, before, after, result)
            if isinstance(effect, JsonHooksEffect):
                _json_auxiliary(case, effect, before, after, result)
        if any(isinstance(effect, SkillEffect) for effect in case.effects.effects):
            if expected.skill_lock is None:
                _obstacle(result, "home", ".", "Independent lock expectation unavailable")
            checks.skill_lock(expected.skill_lock, before, after, result)
        _preservation(case, expected, before, after, result)
        _reinstall(case, before, after, result)
        result.complete = not result.obstacles
        return result
