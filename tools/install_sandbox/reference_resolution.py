from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


ReferenceResolutionStatus = Literal[
    "available",
    "empty",
    "intentionally_absent",
    "no_eligible_bundle",
    "missing",
    "not_directory",
]


class ReferenceBundleFact(Protocol):
    name: str

    def is_eligible(self, package_dir: Path) -> bool: ...


class TargetReferenceFacts(Protocol):
    name: str
    uses_packaged_references: bool
    reference_bundles: tuple[ReferenceBundleFact, ...]


@dataclass(frozen=True)
class PackagedReferenceResolution:
    status: ReferenceResolutionStatus
    refs_dir: Path | None = None
    expected_names: tuple[str, ...] = ()
    detail: str = ""

    @property
    def expects_references(self) -> bool:
        return self.status in {"available", "empty", "missing", "not_directory"}


def package_dir_from_main_module(graphify_main: object) -> Path:
    return Path(str(getattr(graphify_main, "__file__"))).parent


def resolve_target_packaged_references(
    target_name: str,
    *,
    graphify_main: object,
    target_reference_facts: TargetReferenceFacts,
) -> PackagedReferenceResolution:
    if target_reference_facts.reference_bundles:
        return _resolve_bundled_references(graphify_main, target_reference_facts)
    if not target_reference_facts.uses_packaged_references:
        return PackagedReferenceResolution(
            "intentionally_absent",
            detail=f"{target_name} does not use packaged references",
        )

    refs_dir = graphify_main._packaged_skill_refs_dir(target_name)
    if refs_dir is None:
        return PackagedReferenceResolution(
            "intentionally_absent",
            detail=f"{target_name} packaged references returned None",
        )
    return _classify_refs_dir(Path(refs_dir), detail_prefix=f"{target_name} legacy packaged references")


def _resolve_bundled_references(
    graphify_main: object,
    target_reference_facts: TargetReferenceFacts,
) -> PackagedReferenceResolution:
    package_dir = package_dir_from_main_module(graphify_main)
    attempted: list[str] = []
    for bundle in target_reference_facts.reference_bundles:
        if not bundle.is_eligible(package_dir):
            attempted.append(f"{bundle.name}:ineligible")
            continue
        bundle_dir = package_dir / "skills" / bundle.name
        if not bundle_dir.is_dir():
            attempted.append(f"{bundle.name}:missing_bundle_dir")
            continue
        refs_dir = bundle_dir / "references"
        return _classify_refs_dir(refs_dir, detail_prefix=f"{target_reference_facts.name} bundle {bundle.name}")
    return PackagedReferenceResolution(
        "no_eligible_bundle",
        detail=(
            f"no eligible reference bundle for {target_reference_facts.name}; "
            f"attempted={', '.join(attempted) or 'none'}"
        ),
    )


def _classify_refs_dir(refs_dir: Path, *, detail_prefix: str) -> PackagedReferenceResolution:
    if not refs_dir.exists():
        return PackagedReferenceResolution(
            "missing",
            refs_dir=refs_dir,
            detail=f"{detail_prefix} references path is missing: {refs_dir}",
        )
    if not refs_dir.is_dir():
        return PackagedReferenceResolution(
            "not_directory",
            refs_dir=refs_dir,
            detail=f"{detail_prefix} references path is not a directory: {refs_dir}",
        )

    names = tuple(sorted(path.name for path in refs_dir.glob("*.md") if path.is_file()))
    if names:
        return PackagedReferenceResolution(
            "available",
            refs_dir=refs_dir,
            expected_names=names,
            detail=f"{detail_prefix} references available: {len(names)} markdown file(s)",
        )
    return PackagedReferenceResolution(
        "empty",
        refs_dir=refs_dir,
        detail=f"{detail_prefix} references directory contains no markdown files: {refs_dir}",
    )
