"""Strict conversion of fictional catalog documents into immutable Target Facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import cast

from .yaml_source import load_yaml_document

_TARGET_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


class Scope(StrEnum):
    """The closed install scopes understood by the Validation Engine."""

    USER = "user"
    PROJECT = "project"


class SurfaceRoot(StrEnum):
    """A logical sandbox root; no host or container path crosses this boundary."""

    HOME = "home"
    XDG = "xdg"
    PROJECT = "project"
    USER_CWD = "user_cwd"


@dataclass(frozen=True, slots=True)
class OwnedFileSurface:
    """A complete Graphify-owned file copied from a prepared package source."""

    root: SurfaceRoot
    path: str
    source: str


@dataclass(frozen=True, slots=True)
class TextEntrySurface:
    """One Graphify-owned entry inside otherwise user-owned text."""

    root: SurfaceRoot
    path: str
    entry: str
    required_text: str


@dataclass(frozen=True, slots=True)
class RepairableBundleSurface:
    """A package-bound file with owned sidecars and version state to repair."""

    root: SurfaceRoot
    path: str
    source: str
    reference_bundle: str


type InstallSurface = OwnedFileSurface | TextEntrySurface | RepairableBundleSurface


class OwnedSurfaceKind(StrEnum):
    OWNED_FILE = "owned_file"
    REPAIRABLE_BUNDLE = "repairable_bundle"


@dataclass(frozen=True, slots=True)
class OwnedSurfaceIdentity:
    kind: OwnedSurfaceKind
    root: SurfaceRoot
    path: str

    @property
    def ownership_key(self) -> str:
        return self.kind.value

    @property
    def sort_key(self) -> tuple[str, ...]:
        return (self.kind.value, self.root.value, self.path)


@dataclass(frozen=True, slots=True)
class SharedEntryIdentity:
    root: SurfaceRoot
    path: str
    entry: str

    @property
    def ownership_key(self) -> str:
        return "text_entry"

    @property
    def sort_key(self) -> tuple[str, ...]:
        return (self.ownership_key, self.root.value, self.path, self.entry)


type SurfaceIdentity = OwnedSurfaceIdentity | SharedEntryIdentity


@dataclass(frozen=True, slots=True)
class SupportedScopeFacts:
    """Target Facts for one supported scope."""

    surfaces: tuple[InstallSurface, ...]
    runtime_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnsupportedScopeFacts:
    """An explicit catalog-owned reason that a target scope cannot run."""

    reason: str
    runtime_limitations: tuple[str, ...]


type ScopeFacts = SupportedScopeFacts | UnsupportedScopeFacts


@dataclass(frozen=True, slots=True)
class TargetScopeFacts:
    scope: Scope
    facts: ScopeFacts


@dataclass(frozen=True, slots=True)
class TargetFacts:
    """Deeply immutable facts derived from one filename-owned target document."""

    name: str
    scopes: tuple[TargetScopeFacts, ...]

    def facts_for(self, scope: Scope) -> ScopeFacts:
        for item in self.scopes:
            if item.scope is scope:
                return item.facts
        raise ValueError(f"target {self.name!r} does not classify {scope.value!r}")


@dataclass(frozen=True, slots=True)
class InstallTargetCatalog:
    """The lexical, filename-derived set of Install Targets."""

    targets: tuple[TargetFacts, ...]

    def target(self, name: str) -> TargetFacts | None:
        return next((target for target in self.targets if target.name == name), None)


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    filename: str
    text: str


class CatalogReadError(ValueError):
    """The filesystem catalog boundary could not produce trusted documents."""


@dataclass(frozen=True, slots=True)
class CatalogDocuments:
    documents: tuple[CatalogDocument, ...]

    @classmethod
    def from_directory(cls, directory: Path) -> CatalogDocuments:
        """Read filename-owned YAML documents from one catalog directory."""

        try:
            if directory.is_symlink() or not directory.is_dir():
                raise CatalogReadError(f"catalog directory is not a real directory: {directory}")
            paths = sorted(directory.glob("*.yaml"), key=lambda path: path.name)
            documents: list[CatalogDocument] = []
            for path in paths:
                if path.is_symlink() or not path.is_file():
                    raise CatalogReadError(f"catalog document is not a regular file: {path}")
                documents.append(CatalogDocument(path.name, path.read_text(encoding="utf-8")))
            return cls(tuple(documents))
        except OSError as error:
            raise CatalogReadError(f"cannot read catalog directory {directory}: {error}") from error


@dataclass(frozen=True, slots=True)
class CatalogAccepted:
    catalog: InstallTargetCatalog


@dataclass(frozen=True, slots=True)
class CatalogRejected:
    reasons: tuple[str, ...]


type CatalogCompilation = CatalogAccepted | CatalogRejected


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping with string keys")
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError(f"{label} must be a mapping with string keys")
    return cast(Mapping[str, object], mapping)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual)) or "none"
        unknown = ", ".join(sorted(actual - expected)) or "none"
        raise ValueError(f"{label} fields differ: missing={missing}; unknown={unknown}")


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of non-empty strings")
    raw = cast(list[object], value)
    if not all(isinstance(item, str) and item.strip() for item in raw):
        raise ValueError(f"{label} must be a list of non-empty strings")
    strings = tuple(cast(str, item) for item in raw)
    if len(strings) != len(set(strings)):
        raise ValueError(f"{label} must not contain duplicates")
    return strings


def _safe_relative(value: object, label: str) -> str:
    text = _nonempty_string(value, label)
    path = PurePosixPath(text)
    if (
        not path.parts
        or path.is_absolute()
        or str(path) != text
        or text.strip() != text
        or any(part == ".." for part in path.parts)
        or "\\" in text
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise ValueError(f"{label} must be a canonical safe relative path")
    return text


def _safe_leaf(value: object, label: str) -> str:
    text = _safe_relative(value, label)
    if len(PurePosixPath(text).parts) != 1:
        raise ValueError(f"{label} must be a canonical safe path leaf")
    return text


def _surface(value: object, label: str) -> InstallSurface:
    raw = _mapping(value, label)
    kind = _nonempty_string(raw.get("kind"), f"{label}.kind")
    try:
        root = SurfaceRoot(_nonempty_string(raw.get("root"), f"{label}.root"))
    except ValueError as error:
        raise ValueError(f"{label}.root is invalid") from error
    path = _safe_relative(raw.get("path"), f"{label}.path")
    if kind == "owned_file":
        _exact_keys(raw, frozenset({"kind", "root", "path", "source"}), label)
        return OwnedFileSurface(root, path, _safe_relative(raw["source"], f"{label}.source"))
    if kind == "text_entry":
        _exact_keys(
            raw,
            frozenset({"kind", "root", "path", "entry", "required_text"}),
            label,
        )
        return TextEntrySurface(
            root,
            path,
            _nonempty_string(raw["entry"], f"{label}.entry"),
            _nonempty_string(raw["required_text"], f"{label}.required_text"),
        )
    if kind == "repairable_bundle":
        _exact_keys(
            raw,
            frozenset({"kind", "root", "path", "source", "reference_bundle"}),
            label,
        )
        return RepairableBundleSurface(
            root,
            path,
            _safe_relative(raw["source"], f"{label}.source"),
            _safe_leaf(raw["reference_bundle"], f"{label}.reference_bundle"),
        )
    raise ValueError(f"{label}.kind is unknown: {kind!r}")


def surface_identity(surface: InstallSurface) -> SurfaceIdentity:
    """Return the catalog-independent ownership identity of one Install Surface."""

    if isinstance(surface, OwnedFileSurface):
        return OwnedSurfaceIdentity(OwnedSurfaceKind.OWNED_FILE, surface.root, surface.path)
    if isinstance(surface, TextEntrySurface):
        return SharedEntryIdentity(surface.root, surface.path, surface.entry)
    return OwnedSurfaceIdentity(OwnedSurfaceKind.REPAIRABLE_BUNDLE, surface.root, surface.path)


def _scope_facts(value: object, label: str) -> ScopeFacts:
    raw = _mapping(value, label)
    supported = raw.get("supported")
    if supported is True:
        _exact_keys(
            raw,
            frozenset({"supported", "surfaces", "runtime_limitations"}),
            label,
        )
        raw_surfaces = raw["surfaces"]
        if not isinstance(raw_surfaces, list) or not raw_surfaces:
            raise ValueError(f"{label}.surfaces must be a non-empty list")
        surfaces = tuple(
            _surface(item, f"{label}.surfaces[{index}]")
            for index, item in enumerate(cast(list[object], raw_surfaces))
        )
        identities = tuple(surface_identity(surface) for surface in surfaces)
        if len(identities) != len(set(identities)):
            raise ValueError(f"{label}.surfaces contains duplicate classifications")
        owned_locations = {
            (surface.root, surface.path)
            for surface in surfaces
            if not isinstance(surface, TextEntrySurface)
        }
        shared_locations = {
            (surface.root, surface.path)
            for surface in surfaces
            if isinstance(surface, TextEntrySurface)
        }
        if owned_locations & shared_locations:
            raise ValueError(f"{label}.surfaces has conflicting Install Surface ownership")
        return SupportedScopeFacts(
            surfaces,
            _strings(raw["runtime_limitations"], f"{label}.runtime_limitations"),
        )
    if supported is False:
        _exact_keys(
            raw,
            frozenset({"supported", "reason", "runtime_limitations"}),
            label,
        )
        return UnsupportedScopeFacts(
            _nonempty_string(raw["reason"], f"{label}.reason"),
            _strings(raw["runtime_limitations"], f"{label}.runtime_limitations"),
        )
    raise ValueError(f"{label}.supported must be a boolean")


def _target_name(filename: str) -> str:
    path = PurePosixPath(filename)
    if len(path.parts) != 1 or path.suffix != ".yaml" or _TARGET_NAME.fullmatch(path.stem) is None:
        raise ValueError(f"catalog filename must be one safe <target>.yaml leaf: {filename!r}")
    return path.stem


def _target(document: CatalogDocument) -> TargetFacts:
    name = _target_name(document.filename)
    loaded = load_yaml_document(document.text, document.filename)
    raw = _mapping(loaded, document.filename)
    _exact_keys(raw, frozenset({"scopes"}), document.filename)
    scopes = _mapping(raw["scopes"], f"{document.filename}.scopes")
    _exact_keys(scopes, frozenset(scope.value for scope in Scope), f"{document.filename}.scopes")
    return TargetFacts(
        name,
        tuple(
            TargetScopeFacts(
                scope,
                _scope_facts(scopes[scope.value], f"{document.filename}.{scope.value}"),
            )
            for scope in Scope
        ),
    )


def _catalog_surface_conflict(targets: list[TargetFacts]) -> str | None:
    by_identity: dict[SurfaceIdentity, InstallSurface] = {}
    ownership: dict[tuple[SurfaceRoot, str], str] = {}
    for target in targets:
        for scoped in target.scopes:
            if not isinstance(scoped.facts, SupportedScopeFacts):
                continue
            for surface in scoped.facts.surfaces:
                identity = surface_identity(surface)
                existing = by_identity.get(identity)
                if existing is not None and existing != surface:
                    return f"catalog targets disagree about Install Surface {identity!r}"
                by_identity[identity] = surface
                location = (surface.root, surface.path)
                owner = identity.ownership_key
                existing_owner = ownership.get(location)
                if existing_owner is not None and existing_owner != owner:
                    printable = (surface.root.value, surface.path)
                    return f"catalog targets disagree about ownership at {printable!r}"
                ownership[location] = owner
    return None


def compile_catalog(documents: CatalogDocuments) -> CatalogCompilation:
    """Validate every document before exposing one immutable catalog."""

    targets: list[TargetFacts] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for document in sorted(documents.documents, key=lambda item: item.filename):
        try:
            target = _target(document)
            if target.name in seen:
                raise ValueError(f"duplicate target document: {target.name!r}")
            seen.add(target.name)
            targets.append(target)
        except ValueError as error:
            reasons.append(str(error))
    if not targets and not reasons:
        reasons.append("catalog must contain at least one target document")
    if reasons:
        return CatalogRejected(tuple(reasons))
    surface_conflict = _catalog_surface_conflict(targets)
    if surface_conflict is not None:
        return CatalogRejected((surface_conflict,))
    return CatalogAccepted(InstallTargetCatalog(tuple(sorted(targets, key=lambda item: item.name))))
