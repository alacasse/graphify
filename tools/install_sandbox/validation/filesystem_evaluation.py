"""Interpret filesystem Raw Facts against catalog-owned surface semantics."""

from __future__ import annotations

from pathlib import PurePosixPath

from .catalog import OwnedFileSurface, RepairableBundleSurface, SurfaceRoot, TextEntrySurface
from .plan_types import PhasePlan
from .protocol import (
    CommandFact,
    EntryFact,
    EntryKind,
    HarnessFileSurface,
    ManagedTreeSurface,
    ObservationFact,
    PreparedSourcePath,
    SandboxPath,
    SurfaceExpectation,
    SurfaceFact,
)
from .results import ProductFinding


def _entry_problem(entry: EntryFact, label: str) -> str | None:
    if entry.error is not None:
        return f"{label} observation failed: {entry.error}"
    if entry.kind is EntryKind.FILE and (entry.content is None or not entry.content.complete):
        return f"{label} content capture is incomplete"
    return None


def _owned_payload_findings(
    surface: OwnedFileSurface | RepairableBundleSurface,
    surface_fact: SurfaceFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    source = surface_fact.source
    if source is None or source.kind is not EntryKind.FILE or source.content is None:
        return (), (f"prepared source for {surface.path} is unavailable",)
    destination = surface_fact.destination
    assert destination.content is not None
    if destination.content.data == source.content.data:
        return (), ()
    return (
        (
            ProductFinding(
                "payload equality",
                f"{surface.path} differs from {surface.source}",
            ),
        ),
        (),
    )


def _text_entry_findings(
    surface: TextEntrySurface,
    destination: EntryFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    assert destination.content is not None
    try:
        text = destination.content.data.decode("utf-8")
    except UnicodeDecodeError:
        return (), (f"{surface.path} is not valid UTF-8",)
    findings: list[ProductFinding] = []
    if sum(line.strip() == surface.entry for line in text.splitlines()) != 1:
        findings.append(
            ProductFinding(
                "owned text entry",
                f"{surface.entry!r} does not occur exactly once",
            )
        )
    if surface.required_text not in text:
        findings.append(ProductFinding("required text", f"{surface.required_text!r} is absent"))
    return tuple(findings), ()


def _installed_surface(
    surface_fact: SurfaceFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    surface = surface_fact.surface
    destination = surface_fact.destination
    problems = tuple(
        problem
        for problem in (
            _entry_problem(destination, "destination"),
            _entry_problem(surface_fact.source, "prepared source")
            if surface_fact.source is not None
            else None,
        )
        if problem is not None
    )
    if problems:
        return (), problems
    harness_result = _installed_harness_surface(surface_fact)
    if harness_result is not None:
        return harness_result
    if destination.kind is not EntryKind.FILE or destination.content is None:
        return (
            (ProductFinding("installed surface", f"{surface.path} is not a regular file"),),
            (),
        )
    if isinstance(surface, RepairableBundleSurface):
        return (), ("repairable bundle semantic evidence is not implemented in this slice",)
    if isinstance(surface, OwnedFileSurface):
        return _owned_payload_findings(surface, surface_fact)
    assert isinstance(surface, TextEntrySurface)
    return _text_entry_findings(surface, destination)


def _installed_harness_surface(
    surface_fact: SurfaceFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]] | None:
    surface = surface_fact.surface
    destination = surface_fact.destination
    if isinstance(surface, ManagedTreeSurface):
        if destination.kind is EntryKind.DIRECTORY:
            return (), ()
        return (
            (ProductFinding("preserved tree", f"{surface.path} is not a directory"),),
            (),
        )
    if isinstance(surface, HarnessFileSurface):
        if destination.kind is not EntryKind.FILE or destination.content is None:
            return (
                (ProductFinding("preserved sentinel", f"{surface.path} is not a file"),),
                (),
            )
        if destination.content.data == surface.content:
            return (), ()
        return (
            (ProductFinding("preserved sentinel", f"{surface.path} content changed"),),
            (),
        )
    return None


def _absent_surface(
    surface_fact: SurfaceFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    surface = surface_fact.surface
    destination = surface_fact.destination
    problem = _entry_problem(destination, "destination")
    if problem is not None:
        return (), (problem,)
    if isinstance(surface, TextEntrySurface) and destination.kind is EntryKind.FILE:
        assert destination.content is not None
        try:
            text = destination.content.data.decode("utf-8")
        except UnicodeDecodeError:
            return (), (f"{surface.path} is not valid UTF-8",)
        removed = surface.entry not in {line.strip() for line in text.splitlines()}
    else:
        removed = destination.kind is EntryKind.MISSING
    if removed:
        return (), ()
    return (
        (ProductFinding("owned surface removal", f"{surface.path} remains installed"),),
        (),
    )


def _observation_evidence(
    phase: PhasePlan,
    fact: ObservationFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    request = phase.observation
    if len(fact.surfaces) != len(request.surfaces):
        return (), ("filesystem observation cardinality disagrees with the plan",)
    findings: list[ProductFinding] = []
    problems: list[str] = []
    for expected, expectation, observed in zip(
        request.surfaces,
        request.expectations,
        fact.surfaces,
        strict=True,
    ):
        if observed.surface != expected:
            problems.append("filesystem observation surface disagrees with the plan")
            continue
        if observed.destination.location != SandboxPath(expected.root, expected.path):
            problems.append("filesystem observation destination disagrees with the plan")
            continue
        if isinstance(expected, (OwnedFileSurface, RepairableBundleSurface)) and (
            observed.source is None
            or observed.source.location != PreparedSourcePath(expected.source)
        ):
            problems.append("prepared-source observation disagrees with the plan")
            continue
        evaluator = (
            _absent_surface if expectation is SurfaceExpectation.ABSENT else _installed_surface
        )
        surface_findings, surface_problems = evaluator(observed)
        findings.extend(surface_findings)
        problems.extend(surface_problems)
    return tuple(findings), tuple(problems)


def _allowed_changes(phase: PhasePlan) -> frozenset[tuple[SurfaceRoot, str]]:
    allowed: set[tuple[SurfaceRoot, str]] = set()
    for surface in phase.surfaces:
        path = PurePosixPath(surface.path)
        allowed.add((surface.root, path.as_posix()))
        for parent in path.parents:
            if parent != PurePosixPath("."):
                allowed.add((surface.root, parent.as_posix()))
        if isinstance(surface, RepairableBundleSurface):
            allowed.add((surface.root, (path.parent / ".graphify_version").as_posix()))
            allowed.add((surface.root, (path.parent / "references").as_posix()))
            allowed.add((surface.root, (path.parent / "references.tmp").as_posix()))
    return frozenset(allowed)


def _change_is_allowed(
    phase: PhasePlan,
    allowed: frozenset[tuple[SurfaceRoot, str]],
    location: tuple[SurfaceRoot, str],
) -> bool:
    if location in allowed:
        return True
    root, path = location
    return any(
        root is surface.root and (path == surface.path or path.startswith(f"{surface.path}/"))
        for surface in phase.surfaces
        if isinstance(surface, ManagedTreeSurface)
    )


def _snapshot_evidence(
    phase: PhasePlan,
    command: CommandFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    entries = (*command.before_snapshot.entries, *command.after_snapshot.entries)
    errors = tuple(
        f"filesystem snapshot failed at {entry.root.value}:{entry.path}: {entry.error}"
        for entry in entries
        if entry.error is not None
    )
    if errors:
        return (), errors
    before = {(entry.root, entry.path): entry for entry in command.before_snapshot.entries}
    after = {(entry.root, entry.path): entry for entry in command.after_snapshot.entries}
    changed = {
        location
        for location in set(before) | set(after)
        if before.get(location) != after.get(location)
    }
    allowed = _allowed_changes(phase)
    unexpected = sorted(
        (location for location in changed if not _change_is_allowed(phase, allowed, location)),
        key=lambda item: (item[0].value, item[1]),
    )
    if not unexpected:
        return (), ()
    preview = ", ".join(f"{root.value}:{path}" for root, path in unexpected[:8])
    if len(unexpected) > 8:
        preview += f", and {len(unexpected) - 8} more"
    return (
        (
            ProductFinding(
                "filesystem changes stay within declared surfaces",
                f"undeclared changed paths: {preview}",
            ),
        ),
        (),
    )


def evaluate_filesystem(
    phase: PhasePlan,
    command: CommandFact,
    observation: ObservationFact,
) -> tuple[tuple[ProductFinding, ...], tuple[str, ...]]:
    """Return semantic findings and incomplete-evidence problems for one phase."""

    snapshot_findings, snapshot_problems = _snapshot_evidence(phase, command)
    surface_findings, surface_problems = _observation_evidence(phase, observation)
    return (*snapshot_findings, *surface_findings), (*snapshot_problems, *surface_problems)
