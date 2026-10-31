"""Explicit, serializable installation constraints with retained provenance."""

import base64
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.contracts.spec import HookExpectation, fields, text

_PHASES = {"initial", "install", "intermediate", "reinstall"}
_KINDS = {"file", "directory", "absent", "markdown", "markdown-composed", "json-hooks"}


def _decode(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected base64 encoded bytes")
    return base64.b64decode(value, validate=True)


def _encode(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


@dataclass(frozen=True, eq=False)
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
        if self.kind not in _KINDS or self.phase not in _PHASES or not self.provenance:
            raise ValueError("Invalid expectation kind, phase or provenance")
        if self.path == ".":
            if self.root not in {"home", "project"}:
                raise ValueError("Invalid expectation root")
        else:
            Destination(self.root, self.path)
        if self.kind in {"file", "markdown", "markdown-composed"} and self.content is None:
            raise ValueError("Expected explicit file content")
        if self.kind in {"markdown", "markdown-composed"} and (
            self.baseline is None or self.marker is None
        ):
            raise ValueError("Expected Markdown marker and personal baseline")
        if self.kind == "json-hooks" and (self.baseline is None or not self.hooks):
            raise ValueError("Expected JSON hooks and personal baseline")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Expectation) and self.to_data() == other.to_data()

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
        data = fields(
            value,
            "kind root path phase provenance content baseline marker hooks"
            + (
                " initial_prefix"
                if isinstance(value, dict)
                and cast(dict[str, object], value).get("kind") == "markdown-composed"
                else ""
            ),
        )
        hooks = data["hooks"]
        if not isinstance(hooks, list):
            raise ValueError("Expected hook constraints")
        owner = {
            "markdown-composed": ComposedMarkdownExpectation,
            "file": ExactDocumentExpectation,
        }.get(text(data["kind"]), cls)
        item = owner(
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
        if data["kind"] == "markdown-composed":
            item = replace(item, initial_prefix=_decode(data["initial_prefix"]))
        return item


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

    def __post_init__(self) -> None:
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
        _validate_roots(self.roots)

    def to_data(self) -> dict[str, object]:
        return {
            "format": "explicit-expectations-v2",
            "phase": self.phase,
            "expectations": [item.to_data() for item in self.expectations],
            "allowed_changes": [list(item) for item in self.allowed_changes],
            "baseline": [item.to_data() for item in self.baseline],
            "roots": self.roots,
            "lock_destination": None
            if self.lock_destination is None
            else {"root": self.lock_destination.root, "path": self.lock_destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "ExpectationSet":
        data = fields(
            value, "format phase expectations allowed_changes baseline roots lock_destination"
        )
        if data["format"] != "explicit-expectations-v2":
            raise ValueError("Unsupported expectations transport")
        for key in ("expectations", "allowed_changes", "baseline"):
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
        )

    def in_phase(self, phase: str) -> "ExpectationSet":
        return replace(
            self,
            phase=phase,
            expectations=tuple(replace(e, phase=phase) for e in self.expectations),
            baseline=tuple(replace(e, phase=phase) for e in self.baseline),
        )


@dataclass(frozen=True, eq=False)
class ExactDocumentExpectation(Expectation):
    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            self.kind != "file"
            or self.baseline is not None
            or self.marker is not None
            or self.hooks
        ):
            raise ValueError("Exact document accepts only exact content")

    def verify(self, observation: "FilesystemSnapshot", result: VerificationResult) -> None:
        from tools.install_sandbox.container.comparison import compare_bytes

        assert self.content is not None
        compare_bytes(observation, self.path, self.content, result, self.root)


@dataclass(frozen=True, eq=False)
class ComposedMarkdownExpectation(Expectation):
    initial_prefix: bytes = b""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.kind != "markdown-composed" or self.hooks:
            raise ValueError("Invalid composed Markdown expectation")

    def to_data(self) -> dict[str, object]:
        return {**super().to_data(), "initial_prefix": _encode(self.initial_prefix)}

    def verify(self, observation: "FilesystemSnapshot", result: VerificationResult) -> None:
        from tools.install_sandbox.container.comparison import file, verify_markdown_composed

        assert self.content is not None and self.baseline is not None and self.marker is not None
        current = file(observation, self.path, result, self.root)
        if current is not None:
            verify_markdown_composed(
                self.content,
                self.baseline,
                current,
                result,
                root=self.root,
                path=self.path,
                marker=self.marker,
            )


@dataclass(frozen=True)
class PhysicalPreservation:
    baseline: tuple[Expectation, ...]
    permitted_content_changes: tuple[tuple[str, str], ...]

    def verify(self, observed: "FilesystemSnapshot", result: VerificationResult) -> None:
        from tools.install_sandbox.container.comparison import mismatch

        before = {(e.root, e.path): e for e in self.baseline}
        after = {(e["root"], e["path"]): e for e in observed.entries}
        for key in sorted(before.keys() | after.keys()):
            prior, current = before.get(key), after.get(key)
            if key in self.permitted_content_changes and (
                prior is None or (current is not None and prior.kind == current["kind"])
            ):
                continue
            if (
                prior is not None
                and current is not None
                and prior.kind == current["kind"]
                and (prior.kind == "directory" or prior.content == observed.contents.get(key))
            ):
                continue
            mismatch(
                result,
                "unexpected_change",
                *key,
                "entry preserved",
                "entry added, removed or changed",
            )
