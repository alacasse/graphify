"""Managed JSON hooks: exact ownership and recoverable local Linux transactions."""

from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
import math
import os
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any, NoReturn


class ManagedJSONError(ValueError):
    """A safe, content-free managed-hook diagnostic."""


def _fail(message: str) -> NoReturn:
    raise ManagedJSONError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate JSON key")
        result[key] = value
    return result


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        _fail("non-finite JSON value")
    return number


def _constant(_value):
    _fail("non-finite JSON value")


def _load(data: bytes) -> Any:
    try:
        return json.loads(
            data, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float
        )
    except ManagedJSONError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _fail("invalid JSON")


def _bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _exact(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_exact(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_exact(a, b) for a, b in zip(left, right))
    return left == right


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail("invalid document shape")


def _snapshot(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        _fail("unexpected filesystem type")
    return (path.read_bytes(), stat.S_IMODE(info.st_mode))


def _write(path, snapshot, transaction=None):
    if snapshot is None:
        _fail("unsupported file removal")
    data, mode = snapshot
    suffix = transaction + "-" if transaction is not None else ""
    fd, name = tempfile.mkstemp(prefix=path.name + ".graphify-tmp-" + suffix, dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _checkpoint(_stage):
    """Private test seam; never controlled by environment or public CLI."""


def _effects(effects):
    if not isinstance(effects, list) or not effects:
        _fail("effects must be a nonempty list")
    identities = set()
    for effect in effects:
        _keys(effect, ("id", "event", "matcher", "content"))
        for key in ("id", "event", "matcher"):
            if not isinstance(effect[key], str) or not effect[key]:
                _fail("invalid effect identity or context")
        if not isinstance(effect["content"], dict) or not effect["content"]:
            _fail("invalid hook content")
        if effect["id"] in identities:
            _fail("duplicate effect identity")
        identities.add(effect["id"])
    try:
        _load(_bytes(effects))
    except (ValueError, TypeError):
        _fail("invalid finite JSON effects")


def _settings(value):
    if not isinstance(value, dict):
        _fail("configuration must be an object")
    hooks = value.get("hooks", {})
    if not isinstance(hooks, dict):
        _fail("hooks must be an object")
    for groups in hooks.values():
        if not isinstance(groups, list):
            _fail("hook event must be a list")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("matcher"), str):
                _fail("invalid hook group")
            if not isinstance(group.get("hooks"), list) or any(
                not isinstance(h, dict) for h in group["hooks"]
            ):
                _fail("invalid hooks list")
    if "instructions" in value and not isinstance(value["instructions"], list):
        _fail("instructions must be a list")


def _locations(settings, effect, subset=False):
    found = []
    for gi, group in enumerate(settings.get("hooks", {}).get(effect["event"], [])):
        if group["matcher"] != effect["matcher"]:
            continue
        for hi, hook in enumerate(group["hooks"]):
            matches = (
                all(k in hook and _exact(hook[k], v) for k, v in effect["content"].items())
                if subset
                else _exact(hook, effect["content"])
            )
            if matches:
                found.append((gi, hi))
    return found


def _registry(value, target):
    _keys(value, ("version", "owner", "target", "effects"))
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["owner"] != "graphify"
        or value["target"] != target
    ):
        _fail("unknown or inconsistent registry")
    _effects(value["effects"])


def _resolution(value, target, before, desired):
    _keys(value, ("version", "target", "snapshot_sha256", "registry_absent", "effects"))
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["target"] != target
        or value["registry_absent"] is not True
    ):
        _fail("invalid resolution binding")
    if before is None or value["snapshot_sha256"] != hashlib.sha256(before[0]).hexdigest():
        _fail("stale resolution snapshot")
    if not isinstance(value["effects"], list):
        _fail("invalid resolution effects")
    choices = {}
    for choice in value["effects"]:
        if not isinstance(choice, dict):
            _fail("invalid resolution selection")
        action = choice.get("action")
        keys = (
            ("id", "action")
            if action == "create"
            else ("id", "action", "event", "matcher", "group_index", "hook_index", "content")
        )
        _keys(choice, keys)
        if (
            action not in ("create", "adopt")
            or not isinstance(choice["id"], str)
            or choice["id"] in choices
        ):
            _fail("invalid resolution selection")
        choices[choice["id"]] = choice
    if set(choices) != {e["id"] for e in desired}:
        _fail("resolution identities differ")
    return choices


def _plan(settings, registry, desired, resolution, relative, before):
    result = copy.deepcopy(settings)
    choices = None
    if registry is not None:
        if resolution is not None:
            _fail("resolution requires absent registry")
        previous = {e["id"]: e for e in registry["effects"]}
        if set(previous) != {e["id"] for e in desired}:
            _fail("managed identities differ")
    else:
        previous = {}
        if resolution is not None:
            choices = _resolution(resolution, relative, before, desired)
    selected = set()
    for effect in desired:
        old = previous.get(effect["id"])
        choice = choices[effect["id"]] if choices else None
        if old is not None:
            if (old["event"], old["matcher"]) != (effect["event"], effect["matcher"]):
                _fail("managed context changed")
            locations = _locations(settings, old)
        elif choice and choice["action"] == "adopt":
            if (choice["event"], choice["matcher"]) != (effect["event"], effect["matcher"]):
                _fail("adoption context differs")
            locations = _locations(settings, choice)
            if (
                type(choice["group_index"]) is not int
                or type(choice["hook_index"]) is not int
                or locations != [(choice["group_index"], choice["hook_index"])]
            ):
                _fail("adoption selection is not exact and unique")
        else:
            groups = settings.get("hooks", {}).get(effect["event"], [])
            if not choice and any(g["matcher"] == effect["matcher"] and g["hooks"] for g in groups):
                _fail("preexisting hooks require explicit resolution")
            result.setdefault("hooks", {}).setdefault(effect["event"], []).append(
                {"matcher": effect["matcher"], "hooks": [copy.deepcopy(effect["content"])]}
            )
            continue
        if len(locations) != 1:
            _fail("managed hook missing, customized, or duplicated")
        gi, hi = locations[0]
        location = (effect["event"], gi, hi)
        if location in selected:
            _fail("duplicate adoption selection")
        selected.add(location)
        result["hooks"][effect["event"]][gi]["hooks"][hi] = copy.deepcopy(effect["content"])
    for effect in desired:
        if len(_locations(result, effect, subset=True)) != 1:
            _fail("desired hook collision")
    return result


def _encoded(snapshot):
    if snapshot is None:
        return None
    data, mode = snapshot
    return {
        "bytes": base64.b64encode(data).decode(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode": mode,
    }


def _decoded(value):
    if value is None:
        return None
    _keys(value, ("bytes", "sha256", "mode"))
    try:
        data = base64.b64decode(value["bytes"], validate=True)
    except (ValueError, TypeError):
        _fail("invalid journal bytes")
    if (
        type(value["mode"]) is not int
        or not 0 <= value["mode"] <= 0o7777
        or hashlib.sha256(data).hexdigest() != value["sha256"]
    ):
        _fail("invalid journal snapshot")
    return data, value["mode"]


def _journal(value, target):
    _keys(value, ("version", "target_name", "transaction", "request", "target", "registry"))
    if type(value["version"]) is not int or value["version"] != 1 or value["target_name"] != target:
        _fail("invalid journal binding")
    transaction = value["transaction"]
    if (
        not isinstance(transaction, str)
        or len(transaction) != 32
        or any(c not in "0123456789abcdef" for c in transaction)
    ):
        _fail("invalid transaction identity")
    request = value["request"]
    _keys(request, ("effects", "instruction", "resolution_sha256"))
    _effects(request["effects"])
    if not isinstance(request["instruction"], str) or not request["instruction"]:
        _fail("invalid journal instruction")
    digest = request["resolution_sha256"]
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        _fail("invalid journal resolution digest")
    snapshots = {}
    for key in ("target", "registry"):
        _keys(value[key], ("before", "after"))
        for phase in ("before", "after"):
            snapshot = _decoded(value[key][phase])
            if snapshot is None:
                if phase == "after":
                    _fail("missing journal final snapshot")
                continue
            if key == "registry" and snapshot[1] != 0o600:
                _fail("invalid journal registry mode")
            parsed = _load(snapshot[0])
            if key == "target":
                _settings(parsed)
            else:
                _registry(parsed, target)
            snapshots[(key, phase)] = parsed
    final_settings = snapshots[("target", "after")]
    final_registry = snapshots[("registry", "after")]
    if not _exact(final_registry["effects"], request["effects"]):
        _fail("journal registry differs from request")
    if request["instruction"] not in final_settings.get("instructions", []):
        _fail("journal instruction absent from final state")
    for effect in request["effects"]:
        if (
            len(_locations(final_settings, effect)) != 1
            or len(_locations(final_settings, effect, subset=True)) != 1
        ):
            _fail("journal hook differs from request")
    target_before = _decoded(value["target"]["before"])
    target_after = _decoded(value["target"]["after"])
    if target_after is None:
        _fail("missing journal final snapshot")
    if target_after[1] != (target_before[1] if target_before else 0o600):
        _fail("journal target mode differs")


def _finish(paths, journal):
    pairs = []
    for key in ("target", "registry"):
        _keys(journal[key], ("before", "after"))
        before, after = (_decoded(journal[key][k]) for k in ("before", "after"))
        if after is None:
            _fail("invalid journal final state")
        pairs.append((before, after))
    current = tuple(_snapshot(p) for p in paths[:2])
    before = tuple(pair[0] for pair in pairs)
    after = tuple(pair[1] for pair in pairs)
    if current not in (after, before, (after[0], before[1])):
        _fail("foreign transaction state; journal preserved")
    for index, path in enumerate(paths[:2]):
        expected = current[index]
        if _snapshot(path) != expected:
            _fail("external change detected")
        if expected != after[index]:
            _write(path, after[index], journal["transaction"])
        _checkpoint("target_replaced" if index == 0 else "registry_replaced")
    if tuple(_snapshot(p) for p in paths[:2]) != after:
        _fail("transaction confirmation failed")
    _checkpoint("before_journal_remove")
    paths[2].unlink()


def apply_managed_hooks(path, *, project_root, effects, instruction, resolution=None):
    """Apply one bounded desired request; resolution is parsed JSON or None."""
    path, project_root = Path(path), Path(project_root)
    _effects(effects)
    if not isinstance(instruction, str) or not instruction:
        _fail("invalid instruction")
    try:
        relative = (
            Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(project_root))).as_posix()
        )
    except ValueError:
        _fail("target outside project")
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            _fail("symlink parent unsupported")
    path.parent.mkdir(parents=True, exist_ok=True)
    state = path.with_name(path.name + ".graphify-state.json")
    lock = path.with_name(path.name + ".graphify.lock")
    journal_path = path.with_name(path.name + ".graphify-journal.json")
    _snapshot(lock)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
    except FileExistsError:
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if (
            not stat.S_ISREG(os.fstat(fd).st_mode)
            or os.fstat(fd).st_size
            or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600
        ):
            _fail("invalid lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("managed hooks busy")
        request = {
            "effects": effects,
            "instruction": instruction,
            "resolution_sha256": hashlib.sha256(_bytes(resolution)).hexdigest()
            if resolution is not None
            else None,
        }
        pending = _snapshot(journal_path)
        if pending is not None:
            if pending[1] != 0o600:
                _fail("invalid journal mode")
            journal = _load(pending[0])
            _journal(journal, path.name)
            _finish((path, state, journal_path), journal)
            if _exact(request, journal["request"]):
                return
        before, registry_before = _snapshot(path), _snapshot(state)
        settings = _load(before[0]) if before is not None else {}
        _settings(settings)
        registry = _load(registry_before[0]) if registry_before is not None else None
        if registry_before is not None:
            if registry_before[1] != 0o600:
                _fail("invalid registry mode")
            _registry(registry, path.name)
        result = _plan(settings, registry, effects, resolution, relative, before)
        instructions = result.setdefault("instructions", [])
        if instruction not in instructions:
            instructions.append(instruction)
        after = (
            before[0] if before is not None and _exact(result, settings) else _bytes(result),
            before[1] if before else 0o600,
        )
        registry_result = {
            "version": 1,
            "owner": "graphify",
            "target": path.name,
            "effects": effects,
        }
        registry_after = (
            registry_before[0]
            if registry_before is not None and _exact(registry, registry_result)
            else _bytes(registry_result),
            0o600,
        )
        if (before, registry_before) == (after, registry_after):
            return
        if (_snapshot(path), _snapshot(state)) != (before, registry_before):
            _fail("external change detected")
        journal = {
            "version": 1,
            "target_name": path.name,
            "transaction": uuid.uuid4().hex,
            "request": request,
            "target": {"before": _encoded(before), "after": _encoded(after)},
            "registry": {"before": _encoded(registry_before), "after": _encoded(registry_after)},
        }
        _write(journal_path, (_bytes(journal), 0o600), journal["transaction"])
        _checkpoint("journal_published")
        _finish((path, state, journal_path), journal)
    finally:
        os.close(fd)


def read_resolution(path):
    """Read a resolution without exposing its personal content in diagnostics."""
    snapshot = _snapshot(Path(path))
    if snapshot is None:
        _fail("resolution file missing")
    value = _load(snapshot[0])
    _keys(value, ("version", "target", "snapshot_sha256", "registry_absent", "effects"))
    return value
