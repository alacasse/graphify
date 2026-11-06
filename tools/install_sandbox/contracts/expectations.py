"""Explicit, serializable installation constraints with retained provenance."""

import base64
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.spec import HookExpectation, fields, text

_PHASES = {
    "initial",
    "install",
    "intermediate",
    "reinstall",
    "uninstall",
    "install-project-1",
    "install-project-2",
}
_KINDS = {
    "file",
    "directory",
    "absent",
    "markdown",
    "markdown-composed",
    "json-hooks",
    "json-hooks-seeded",
    "json-hook-removed",
    "json-hook-altered",
    "json-hook-duplicated",
    "json-hook-repair",
}


def _decode(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected base64 encoded bytes")
    return base64.b64decode(value, validate=True)


def _encode(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _validate_values(content: object, baseline: object, marker: object, hooks: object) -> None:
    if any(value is not None and not isinstance(value, bytes) for value in (content, baseline)):
        raise ValueError("Expected immutable content bytes")
    if marker is not None and (not isinstance(marker, str) or not marker):
        raise ValueError("Expected nonempty Markdown marker")
    if not isinstance(hooks, tuple):
        raise ValueError("Expected immutable hook constraints")
    if any(not isinstance(hook, HookExpectation) for hook in cast(tuple[object, ...], hooks)):
        raise ValueError("Expected immutable hook constraints")


@dataclass(frozen=True)
class Expectation:
    kind: str
    root: str
    path: str
    phase: str
    provenance: str
    content: bytes | None = None
    baseline: bytes | None = None
    marker: str | None = None
    hooks: tuple[HookExpectation, ...] = ()

    def __post_init__(self) -> None:
        _validate_values(self.content, self.baseline, self.marker, self.hooks)
        if self.kind not in _KINDS or self.phase not in _PHASES or not self.provenance:
            raise ValueError("Invalid expectation kind, phase or provenance")
        if self.path == ".":
            if self.root not in {"home", "project"}:
                raise ValueError("Invalid expectation root")
        else:
            Destination(self.root, self.path)
        semantic = {
            "content": self.content,
            "baseline": self.baseline,
            "marker": self.marker,
            "hooks": self.hooks or None,
        }
        present = {key for key, value in semantic.items() if value is not None}
        required: dict[str, set[str]] = {
            "file": {"content"},
            "directory": set(),
            "absent": set(),
            "markdown": {"content", "baseline", "marker"},
            "markdown-composed": {"content", "baseline", "marker"},
            "json-hooks": {"baseline", "hooks"},
            "json-hooks-seeded": {"baseline", "hooks"},
            "json-hook-removed": {"baseline", "hooks"},
            "json-hook-altered": {"baseline", "hooks"},
            "json-hook-duplicated": {"baseline", "hooks"},
            "json-hook-repair": {"baseline", "hooks"},
        }
        if present != required[self.kind]:
            raise ValueError("Expectation fields do not match its kind")
        if (
            self.kind
            in {
                "json-hook-repair",
                "json-hook-removed",
                "json-hook-altered",
                "json-hook-duplicated",
            }
            and len(self.hooks) != 1
        ):
            raise ValueError("JSON hook repair requires exactly one declared target")

    def to_data(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "root": self.root,
            "path": self.path,
            "phase": self.phase,
            "provenance": self.provenance,
            "content": _encode(self.content),
            "baseline": _encode(self.baseline),
            "marker": self.marker,
            "hooks": [
                {"id": h.id, "event": h.event, "matcher": h.matcher, "content": h.content}
                for h in self.hooks
            ],
        }

    @classmethod
    def from_data(cls, value: object) -> "Expectation":
        data = fields(value, "kind root path phase provenance content baseline marker hooks")
        hooks = data["hooks"]
        if not isinstance(hooks, list):
            raise ValueError("Expected hook constraints")
        return cls(
            text(data["kind"]),
            text(data["root"]),
            text(data["path"]),
            text(data["phase"]),
            text(data["provenance"]),
            _decode(data["content"]),
            _decode(data["baseline"]),
            None if data["marker"] is None else text(data["marker"]),
            tuple(HookExpectation.from_data(h) for h in cast(list[object], hooks)),
        )


def _validate_roots(roots: dict[str, str] | None) -> None:
    if roots is None:
        return
    if set(roots) != {"home", "project"}:
        raise ValueError("Expected home and project root bindings")
    for value in roots.values():
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or str(path) != value:
            raise ValueError("Expected normalized absolute root binding")


@dataclass(frozen=True)
class ExpectationSet:
    phase: str
    expectations: tuple[Expectation, ...]
    allowed_changes: tuple[tuple[str, str], ...] = ()
    baseline: tuple[Expectation, ...] = ()
    roots: dict[str, str] | None = None
    lock_destination: Destination | None = None

    allowed_removals: tuple[tuple[str, str], ...] = ()
    new_skill_locks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.new_skill_locks) is not tuple
            or any(
                type(path) is not str
                or not re.fullmatch(r"\.cache/graphify/skill-locks/[0-9a-f]{16}\.lock", path)
                for path in self.new_skill_locks
            )
            or len(set(self.new_skill_locks)) != len(self.new_skill_locks)
            or (self.new_skill_locks and self.phase != "uninstall")
        ):
            raise ValueError("Expected explicit unique uninstall lock paths")
        if self.phase not in _PHASES:
            raise ValueError("Invalid expectations phase")
        if any(item.phase != self.phase for item in self.expectations + self.baseline):
            raise ValueError("Expectation phase differs from bundle phase")
        keys = [(item.root, item.path) for item in self.expectations]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate expectation destination")
        for root, path in self.allowed_changes:
            if path != ".":
                Destination(root, path)
            elif root not in {"home", "project"}:
                raise ValueError("Invalid allowed root")
        self._validate_permissions()
        _validate_roots(self.roots)

    def _validate_permissions(self) -> None:
        if len(self.allowed_changes) != len(set(self.allowed_changes)):
            raise ValueError("Duplicate allowed change")
        if len(self.allowed_removals) != len(set(self.allowed_removals)):
            raise ValueError("Duplicate allowed removal")
        if self.allowed_removals and self.phase not in {"intermediate", "reinstall", "uninstall"}:
            raise ValueError("Removals are only allowed during preparation, reinstall or uninstall")
        for key in self.allowed_removals:
            Destination(*key)
            if key in self.allowed_changes:
                raise ValueError("Removal permission differs from change permission")
            if not any(
                (e.root, e.path) == key and e.kind in {"file", "directory"} for e in self.baseline
            ):
                raise ValueError("Removal requires a baseline file or directory")
            if not any((e.root, e.path) == key and e.kind == "absent" for e in self.expectations):
                raise ValueError("Removal requires an absence expectation")
            self._validate_removed_descendants(key)

    def _validate_removed_descendants(self, key: tuple[str, str]) -> None:
        for entry in self.baseline:
            if (
                entry.root == key[0]
                and entry.path.startswith(key[1] + "/")
                and (entry.root, entry.path) not in self.allowed_removals
            ):
                raise ValueError("Directory removal requires explicit descendant removals")

    def to_data(self) -> dict[str, object]:
        return {
            "format": "explicit-expectations-v4",
            **({"new_skill_locks": list(self.new_skill_locks)} if self.new_skill_locks else {}),
            "phase": self.phase,
            "expectations": [item.to_data() for item in self.expectations],
            "allowed_changes": [list(item) for item in self.allowed_changes],
            "allowed_removals": [list(item) for item in self.allowed_removals],
            "baseline": [item.to_data() for item in self.baseline],
            "roots": None if self.roots is None else dict(self.roots),
            "lock_destination": None
            if self.lock_destination is None
            else {"root": self.lock_destination.root, "path": self.lock_destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "ExpectationSet":
        data = fields(
            {"new_skill_locks": [], **cast(dict[str, object], value)}
            if isinstance(value, dict)
            else value,
            "new_skill_locks format phase expectations allowed_changes allowed_removals "
            "baseline roots lock_destination",
        )
        if data["format"] != "explicit-expectations-v4":
            raise ValueError("Unsupported expectations transport")
        for key in (
            "expectations",
            "allowed_changes",
            "allowed_removals",
            "baseline",
            "new_skill_locks",
        ):
            if not isinstance(data[key], list):
                raise ValueError("Expected expectation lists")
        allowed: list[tuple[str, str]] = []
        for pair in cast(list[object], data["allowed_changes"]):
            if not isinstance(pair, list) or len(cast(list[object], pair)) != 2:
                raise ValueError("Expected allowed destination pair")
            values = cast(list[object], pair)
            allowed.append((text(values[0]), text(values[1])))
        roots = data["roots"]
        if roots is not None and not isinstance(roots, dict):
            raise ValueError("Expected root bindings")
        bindings = (
            None
            if roots is None
            else {text(k): text(v) for k, v in cast(dict[object, object], roots).items()}
        )
        lock = data["lock_destination"]
        return cls(
            text(data["phase"]),
            tuple(Expectation.from_data(e) for e in cast(list[object], data["expectations"])),
            tuple(allowed),
            tuple(Expectation.from_data(e) for e in cast(list[object], data["baseline"])),
            bindings,
            None if lock is None else Destination.from_data(lock),
            tuple(_pair(pair) for pair in cast(list[object], data["allowed_removals"])),
            tuple(text(path) for path in cast(list[object], data["new_skill_locks"])),
        )

    def in_phase(self, phase: str) -> "ExpectationSet":
        return replace(
            self,
            phase=phase,
            expectations=tuple(replace(e, phase=phase) for e in self.expectations),
            baseline=tuple(replace(e, phase=phase) for e in self.baseline),
        )


def _pair(value: object) -> tuple[str, str]:
    if not isinstance(value, list) or len(cast(list[object], value)) != 2:
        raise ValueError("Expected allowed destination pair")
    values = cast(list[object], value)
    return text(values[0]), text(values[1])
