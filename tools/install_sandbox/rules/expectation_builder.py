"""Construct expectations before invocation from retained sources and explicit rules."""

import hashlib
from dataclasses import replace
from email.parser import BytesParser
from pathlib import PurePosixPath

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import (
    JSON_BACKUP_SUFFIX,
    JSON_FORBIDDEN_SUFFIXES,
    Destination,
    FileEffect,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.intermediate import (
    AlteredReferencePreparation,
    AlteredSkillPreparation,
    IntermediatePreparation,
    MissingReferencePreparation,
    PreserveSkillBackupPreparation,
    StaleReferencePreparation,
    StaleVersionPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.rules.effect_verifier import PRESERVATION_CHECK_ROOTS


def retained_bytes(snapshot: FilesystemSnapshot, root: str, path: str) -> bytes:
    entry = snapshot.entry(root, path)
    content = snapshot.contents.get((root, path))
    if entry is None or entry["kind"] != "file" or content is None:
        raise ValueError(f"Retained file unavailable: {root}:{path}")
    return content


def _complete(snapshot: FilesystemSnapshot, roots: tuple[str, ...]) -> None:
    if snapshot.obstacles:
        raise ValueError("Cannot construct expectations from incomplete observations")
    keys = [(e["root"], e["path"]) for e in snapshot.entries]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate observed destination")
    for entry in snapshot.entries:
        if entry["kind"] == "file":
            retained_bytes(snapshot, entry["root"], entry["path"])
        elif entry["kind"] != "directory" or not entry.get("listing_complete"):
            raise ValueError("Incomplete retained inventory")
    for root in roots:
        entry = snapshot.entry(root, ".")
        if entry is None or entry["kind"] != "directory":
            raise ValueError(f"Complete observed root unavailable: {root}")


def _version(case: EffectInstallCase, sources: FilesystemSnapshot) -> bytes:
    content = retained_bytes(sources, "subject", case.subject.version_source)
    versions = BytesParser().parsebytes(content).get_all("Version", [])
    if len(versions) != 1 or not versions[0].strip():
        raise ValueError("Expected exactly one retained metadata Version")
    return versions[0].strip().encode("utf-8")


def _references(effect: SkillEffect, sources: FilesystemSnapshot) -> tuple[Expectation, ...]:
    entry = sources.entry("subject", effect.references)
    if entry is None or entry["kind"] != "directory" or not entry.get("listing_complete"):
        raise ValueError("Complete source references unavailable")
    constraints: list[Expectation] = []
    for source in sources.entries:
        path = source["path"]
        if source["root"] != "subject" or not (
            path == effect.references or path.startswith(effect.references + "/")
        ):
            continue
        destination = effect.destination.path + "/references" + path[len(effect.references) :]
        content = retained_bytes(sources, "subject", path) if source["kind"] == "file" else None
        constraints.append(
            Expectation(
                source["kind"],
                effect.destination.root,
                destination,
                "install",
                "source:subject:" + path,
                content,
            )
        )
    return tuple(constraints)


def _skill_constraints(
    case: EffectInstallCase, effect: SkillEffect, sources: FilesystemSnapshot
) -> tuple[Expectation, ...]:
    root, path = effect.destination.root, effect.destination.path
    return (
        Expectation("directory", root, path, "install", "effect:skill"),
        Expectation(
            "file",
            root,
            path + "/SKILL.md",
            "install",
            "source:subject:" + effect.source,
            retained_bytes(sources, "subject", effect.source),
        ),
        Expectation(
            "file",
            root,
            path + "/.graphify_version",
            "install",
            "version:subject:" + case.subject.version_source,
            _version(case, sources),
        ),
        Expectation(
            "absent",
            root,
            path + "/SKILL.md" + case.subject.rules.skill_backup,
            "install",
            "rule:skill_backup",
        ),
        *_references(effect, sources),
    )


def _source_constraints(case: EffectInstallCase, sources: FilesystemSnapshot) -> None:
    _complete(sources, ())
    for effect in case.effects.effects:
        if isinstance(effect, SkillEffect):
            _skill_constraints(case, effect, sources)
        elif isinstance(effect, MarkdownSectionEffect):
            content = retained_bytes(sources, "subject", effect.source).decode("utf-8")
            if not content.startswith(effect.marker + "\n"):
                raise ValueError("Retained Markdown source does not start with its marker")
            if sum(line == effect.marker for line in content.splitlines()) != 1:
                raise ValueError("Retained Markdown source has duplicate markers")


def _group_initial_expectations(case: EffectInstallCase) -> ExpectationSet:
    initial = [
        Expectation(
            "file",
            f["root"],
            f["path"],
            "initial",
            "case:initial_files",
            f["content"].encode("utf-8"),
        )
        for f in case.initial_files
    ]
    for effect in case.effects.effects:
        if isinstance(effect, FileEffect):
            initial.append(
                Expectation(
                    "absent",
                    effect.destination.root,
                    effect.destination.path,
                    "initial",
                    "effect:file",
                )
            )
        elif isinstance(effect, JsonHooksEffect):
            initial.append(
                Expectation(
                    "absent",
                    effect.destination.root,
                    effect.destination.path + case.subject.rules.json_backup,
                    "initial",
                    "rule:json_backup",
                )
            )
    return ExpectationSet("initial", tuple(initial))


def build_initial_expectations(
    case: EffectInstallCase, sources: FilesystemSnapshot
) -> ExpectationSet:
    """Validate source construction and describe the prepared, uninstalled state."""
    if case.participants:
        return _group_initial_expectations(case)
    _source_constraints(case, sources)
    if isinstance(
        case.intermediate_preparation, (MissingReferencePreparation, AlteredReferencePreparation)
    ):
        selected_reference(case, sources)
    if isinstance(case.intermediate_preparation, StaleReferencePreparation):
        selected_stale_reference(case, sources)
    constraints = [
        Expectation(
            "file",
            f["root"],
            f["path"],
            "initial",
            "case:initial_files",
            f["content"].encode("utf-8"),
        )
        for f in case.initial_files
    ]
    lock = None
    for effect in case.effects.effects:
        root, path = effect.destination.root, effect.destination.path
        if isinstance(effect, FileEffect):
            constraints.append(Expectation("absent", root, path, "initial", "effect:file"))
        elif isinstance(effect, SkillEffect):
            lock = effect.destination
            constraints.extend(
                (
                    Expectation("absent", root, path, "initial", "effect:skill"),
                    Expectation(
                        "absent",
                        root,
                        path + "/SKILL.md" + case.subject.rules.skill_backup,
                        "initial",
                        "rule:skill_backup",
                    ),
                )
            )
        elif isinstance(effect, JsonHooksEffect):
            constraints.append(
                Expectation(
                    "absent",
                    root,
                    path + case.subject.rules.json_backup,
                    "initial",
                    "rule:json_backup",
                )
            )
    return ExpectationSet("initial", tuple(constraints), lock_destination=lock)


def _allowed(constraints: tuple[Expectation, ...]) -> tuple[tuple[str, str], ...]:
    paths: set[tuple[str, str]] = set()
    for item in constraints:
        if item.kind == "absent":
            continue
        paths.add((item.root, item.path))
        paths.update((item.root, str(parent)) for parent in PurePosixPath(item.path).parents)
    return tuple(sorted(paths))


def preservation_baseline(snapshot: FilesystemSnapshot, phase: str) -> tuple[Expectation, ...]:
    _complete(snapshot, PRESERVATION_CHECK_ROOTS)
    return tuple(
        Expectation(
            e["kind"],
            e["root"],
            e["path"],
            phase,
            "observation:prior",
            snapshot.contents.get((e["root"], e["path"])),
        )
        for e in snapshot.entries
    )


def json_forbidden_expectations(effect: JsonHooksEffect) -> tuple[Expectation, ...]:
    return tuple(
        Expectation(
            "absent",
            effect.destination.root,
            effect.destination.path + suffix,
            "install",
            "rule:json_registry",
        )
        for suffix in JSON_FORBIDDEN_SUFFIXES
    )


def json_auxiliary_expectations(
    effect: JsonHooksEffect, before: FilesystemSnapshot
) -> tuple[Expectation, ...]:
    """Shared obligations for the supported backup-without-registry JSON contract."""
    root, path = effect.destination.root, effect.destination.path
    backup = path + JSON_BACKUP_SUFFIX
    origin = backup if before.entry(root, backup) is not None else path
    return (
        Expectation(
            "file",
            root,
            backup,
            "install",
            "observation:prior:" + origin,
            retained_bytes(before, root, origin),
        ),
        *json_forbidden_expectations(effect),
    )


def _json_constraints(
    effect: JsonHooksEffect, before: FilesystemSnapshot
) -> tuple[Expectation, ...]:
    root, path = effect.destination.root, effect.destination.path
    return (
        Expectation(
            "json-hooks",
            root,
            path,
            "install",
            "effect:json-hooks",
            baseline=retained_bytes(before, root, path),
            hooks=effect.hooks,
        ),
        *json_auxiliary_expectations(effect, before),
    )


def _markdown_install_constraint(
    case: EffectInstallCase,
    effect: MarkdownSectionEffect,
    sources: FilesystemSnapshot,
    before: FilesystemSnapshot,
) -> Expectation:
    preparation = case.intermediate_preparation
    content = retained_bytes(sources, "subject", effect.source)
    root, path = effect.destination.root, effect.destination.path
    if (
        isinstance(preparation, IntermediatePreparation)
        and preparation.destination == effect.destination
    ):
        return Expectation(
            "file",
            root,
            path,
            "install",
            "case:fragments+source",
            preparation.before + content + preparation.after,
        )
    return Expectation(
        "markdown",
        root,
        path,
        "install",
        "source:subject:" + effect.source,
        content,
        retained_bytes(before, root, path),
        effect.marker,
    )


def build_install_expectations(
    case: EffectInstallCase,
    sources: FilesystemSnapshot,
    before: FilesystemSnapshot,
    roots: dict[str, str],
) -> ExpectationSet:
    if case.participants:
        return ExpectationSet("install", (), roots=dict(roots))
    _source_constraints(case, sources)
    baseline = preservation_baseline(before, "install")
    constraints: list[Expectation] = []
    lock = None
    for effect in case.effects.effects:
        root, path = effect.destination.root, effect.destination.path
        if isinstance(effect, FileEffect):
            constraints.append(
                Expectation(
                    "file", root, path, "install", "effect:file", effect.content.encode("utf-8")
                )
            )
        elif isinstance(effect, SkillEffect):
            lock = effect.destination
            constraints.extend(_skill_constraints(case, effect, sources))
        elif isinstance(effect, MarkdownSectionEffect):
            constraints.append(_markdown_install_constraint(case, effect, sources, before))
        else:
            constraints.extend(_json_constraints(effect, before))
    if isinstance(case.intermediate_preparation, StaleReferencePreparation):
        destination, source_path = selected_stale_reference(case, sources)
        constraints.append(
            Expectation(
                "absent",
                destination.root,
                destination.path,
                "install",
                "source:absent:" + source_path,
            )
        )
    bundle = ExpectationSet(
        "install", tuple(constraints), _allowed(tuple(constraints)), baseline, lock_destination=lock
    )
    return bind_roots(bundle, roots)


def bind_roots(expectations: ExpectationSet, roots: dict[str, str]) -> ExpectationSet:
    """Resolve root-dependent values once, without accessing the subject filesystem."""
    if expectations.roots is not None:
        if expectations.roots != roots:
            raise ValueError("Expectations already bound to different roots")
        return expectations
    bound = replace(expectations, roots=dict(roots))
    destination = expectations.lock_destination
    if destination is None:
        return bound
    absolute = str(PurePosixPath(roots[destination.root]) / destination.path)
    digest = hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:16]
    path = f".cache/graphify/skill-locks/{digest}.lock"
    kind = "absent" if bound.phase == "initial" else "file"
    constraint = Expectation(
        kind, "home", path, bound.phase, "rule:skill_lock", None if kind == "absent" else b""
    )
    constraints = (*bound.expectations, constraint)
    allowed = () if bound.phase == "initial" else _allowed(constraints)
    return replace(bound, expectations=constraints, allowed_changes=allowed)


def build_reinstall_expectations(
    installed: ExpectationSet, first_after: FilesystemSnapshot, validation: VerificationResult
) -> ExpectationSet:
    """Only validated first-install observations may become preservation expectations."""
    if installed.phase != "install" or installed.roots is None:
        raise ValueError("Reinstall requires bound first-install expectations")
    if not validation.complete or validation.mismatches or validation.obstacles:
        raise ValueError("Reinstall requires a conforming complete first installation")
    return replace(
        installed.in_phase("reinstall"),
        allowed_changes=(),
        baseline=preservation_baseline(first_after, "reinstall"),
    )


def selected_reference(case: EffectInstallCase, sources: FilesystemSnapshot) -> Destination:
    """Select from the complete retained source inventory, never installed output."""
    preparation = case.intermediate_preparation
    if not isinstance(preparation, (MissingReferencePreparation, AlteredReferencePreparation)):
        raise ValueError("Case has no reference preparation")
    preparation.to_data()
    _source_constraints(case, sources)
    effect = next(
        (
            e
            for e in case.effects.effects
            if isinstance(e, SkillEffect) and e.destination == preparation.destination
        ),
        None,
    )
    if effect is None:
        raise ValueError("Reference preparation requires matching skill effect")
    paths = sorted(
        entry["path"]
        for entry in sources.entries
        if entry["root"] == "subject"
        and entry["kind"] == "file"
        and entry["path"].startswith(effect.references + "/")
    )
    if not paths:
        raise ValueError("Reference repair requires a nonempty source reference bundle")
    return Destination(
        effect.destination.root,
        effect.destination.path + "/references/" + paths[0][len(effect.references) + 1 :],
    )


def selected_skill(case: EffectInstallCase) -> Destination:
    """Resolve the skill document from the preparation and declared skill effect."""
    preparation = case.intermediate_preparation
    if not isinstance(preparation, (AlteredSkillPreparation, PreserveSkillBackupPreparation)):
        raise ValueError("Case has no skill preparation")
    preparation.to_data()
    effect = next(
        (
            effect
            for effect in case.effects.effects
            if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
        ),
        None,
    )
    if effect is None:
        raise ValueError("Skill preparation requires matching skill effect")
    return Destination(effect.destination.root, effect.destination.path + "/SKILL.md")


def selected_version(
    case: EffectInstallCase, sources: FilesystemSnapshot
) -> tuple[Destination, bytes, bytes]:
    """Resolve the version file, exact metadata bytes, and a distinct stale witness."""
    preparation = case.intermediate_preparation
    if not isinstance(preparation, StaleVersionPreparation):
        raise ValueError("Case has no stale version preparation")
    preparation.to_data()
    effect = next(
        (
            effect
            for effect in case.effects.effects
            if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
        ),
        None,
    )
    if effect is None:
        raise ValueError("Stale version preparation requires matching skill effect")
    expected = _version(case, sources)
    witness = b"0.0.1-stale" if expected == b"0.0.0-stale" else b"0.0.0-stale"
    return (
        Destination(effect.destination.root, effect.destination.path + "/.graphify_version"),
        expected,
        witness,
    )


def selected_stale_reference(
    case: EffectInstallCase, sources: FilesystemSnapshot
) -> tuple[Destination, str]:
    """Prove the fixed witness is absent from the complete source reference bundle."""
    preparation = case.intermediate_preparation
    if not isinstance(preparation, StaleReferencePreparation):
        raise ValueError("Case has no stale reference preparation")
    preparation.to_data()
    _source_constraints(case, sources)
    effect = next(
        (
            effect
            for effect in case.effects.effects
            if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
        ),
        None,
    )
    if effect is None:
        raise ValueError("Stale reference preparation requires matching skill effect")
    if not sources.absent("subject", effect.references + "/stale.md"):
        raise ValueError("Stale reference witness must be absent from retained sources")
    return (
        Destination(effect.destination.root, effect.destination.path + "/references/stale.md"),
        effect.references + "/stale.md",
    )
