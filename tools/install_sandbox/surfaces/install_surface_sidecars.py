from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

from ..reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus
from .install_surface_models import InstallSurface, SkillSidecarExpectation


ReferenceSidecarMode = Literal["absent", "source_error", "installed_directory"]


@dataclass(frozen=True)
class ReferenceSidecarExpectation:
    status: ReferenceResolutionStatus
    mode: ReferenceSidecarMode
    expected_names: tuple[str, ...]
    detail: str

    @classmethod
    def from_resolution(cls, resolution: PackagedReferenceResolution) -> ReferenceSidecarExpectation:
        if resolution.status in {"intentionally_absent", "no_eligible_bundle"}:
            mode: ReferenceSidecarMode = "absent"
        elif resolution.status in {"missing", "not_directory"}:
            mode = "source_error"
        else:
            mode = "installed_directory"
        return cls(
            status=resolution.status,
            mode=mode,
            expected_names=resolution.expected_names,
            detail=resolution.detail,
        )

    @property
    def includes_reference_dir(self) -> bool:
        return self.mode in {"source_error", "installed_directory"}

    def expected_relatives(self, skill_relative_dir: Path, sidecar: SkillSidecarExpectation) -> set[Path]:
        if not self.includes_reference_dir:
            return set()
        references = skill_relative_dir / sidecar.references_dir
        relatives = {references}
        relatives.update(references / name for name in self.expected_names)
        return relatives


def skill_sidecar_expectation(surface: InstallSurface) -> SkillSidecarExpectation:
    if surface.skill_sidecar_expectation is None:
        raise AssertionError(f"expected path has no skill sidecar expectation: {surface.root}/{surface.relative}")
    return surface.skill_sidecar_expectation


def skill_dir_for_entry(surface: InstallSurface, roots: Mapping[str, Path]) -> Path:
    try:
        root = roots[surface.root]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {surface.root}") from exc
    return (root / surface.relative).parent


def skill_relative_dir(surface: InstallSurface) -> Path:
    return Path(surface.relative).parent


def skill_version_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).version_name


def skill_references_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).references_dir


def skill_references_tmp_relative(surface: InstallSurface) -> Path:
    return skill_relative_dir(surface) / skill_sidecar_expectation(surface).references_tmp_dir


def reference_sidecar_expectation(resolution: PackagedReferenceResolution) -> ReferenceSidecarExpectation:
    return ReferenceSidecarExpectation.from_resolution(resolution)


def expected_skill_sidecar_relatives(surface: InstallSurface, resolution: PackagedReferenceResolution) -> set[Path]:
    sidecar = skill_sidecar_expectation(surface)
    relatives = {
        skill_version_relative(surface),
        skill_references_tmp_relative(surface),
    }
    relatives.update(reference_sidecar_expectation(resolution).expected_relatives(skill_relative_dir(surface), sidecar))
    return relatives


def skill_version_status(version_text: str | None, expected_version: str) -> tuple[bool, str]:
    if version_text is None:
        return False, f"missing; expected={expected_version}"
    actual_version = version_text.strip()
    return actual_version == expected_version, f"actual={actual_version}; expected={expected_version}"


def references_tmp_absence_status(exists: bool) -> tuple[bool, str]:
    return not exists, "present" if exists else "absent"


def installed_reference_sidecar_status(
    expectation: ReferenceSidecarExpectation,
    *,
    references_exists: bool,
    references_is_dir: bool,
    installed_names: Iterable[str],
) -> tuple[bool, str]:
    expected_names = list(expectation.expected_names)
    if expectation.mode == "absent":
        refs_ok = not references_exists
        refs_state = "references_absent" if refs_ok else "references_present"
        return refs_ok, f"{expectation.status}; {refs_state}; {expectation.detail}"
    if expectation.mode == "source_error":
        return False, f"{expectation.status}; {expectation.detail}"
    if not references_exists:
        return False, f"references_missing; status={expectation.status}; expected_names={expected_names}; {expectation.detail}"
    if not references_is_dir:
        return False, f"references_not_directory; status={expectation.status}; expected_names={expected_names}; {expectation.detail}"

    actual_names = list(installed_names)
    missing = sorted(set(expected_names) - set(actual_names))
    extra = sorted(set(actual_names) - set(expected_names))
    refs_ok = not missing and not extra
    refs_detail = f"status={expectation.status}; actual_names={actual_names}; expected_names={expected_names}; missing={missing}; extra={extra}"
    return refs_ok, refs_detail


def skill_reference_pointers(sidecar: SkillSidecarExpectation, skill_text: str) -> list[str]:
    return sorted(set(re.findall(sidecar.reference_pointer_pattern, skill_text)))


def skill_reference_pointer_status(
    sidecar: SkillSidecarExpectation,
    skill_text: str,
    *,
    references_is_dir: bool,
    installed_names: Iterable[str],
) -> tuple[bool, str]:
    mentions_references = bool(re.search(sidecar.reference_pointer_pattern, skill_text)) or f"{sidecar.references_dir}/" in skill_text
    pointers = skill_reference_pointers(sidecar, skill_text)
    if mentions_references and not references_is_dir:
        return False, f"{sidecar.references_dir}_missing; skill_mentions_references=true; pointers={pointers}"
    if pointers:
        installed = set(installed_names)
        missing_pointers = [name for name in pointers if name not in installed]
        return not missing_pointers, f"pointers={pointers}; missing={missing_pointers}"
    return True, "no_reference_pointers"


def uninstalled_skill_sidecar_status(exists: bool) -> tuple[bool, str]:
    return not exists, "sidecar_still_exists" if exists else "removed"
