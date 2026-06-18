from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Iterable, Protocol

try:
    from .expected_effects import InstallSurface, is_skill_effect
    from .install_surface_sidecars import skill_references_relative, skill_references_tmp_relative, skill_version_relative
    from .install_surface_state import USER_SENTINEL
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import InstallSurface, is_skill_effect  # type: ignore[no-redef]
    from install_surface_sidecars import (  # type: ignore[no-redef]
        skill_references_relative,
        skill_references_tmp_relative,
        skill_version_relative,
    )
    from install_surface_state import USER_SENTINEL  # type: ignore[no-redef]


@dataclass(frozen=True)
class GeneratedFileObservation:
    root_name: str
    relative: Path
    suffix: str
    file_size: int | None
    mentions_expected_marker: bool
    expected_key: bool
    skill_sidecar_relative: bool
    excluded_path: bool
    relative_substring_match: bool
    small_text_candidate: bool

    @property
    def path_relevant(self) -> bool:
        return self.expected_key or self.skill_sidecar_relative or self.relative_substring_match

    @property
    def needs_text_marker_match(self) -> bool:
        return not self.excluded_path and not self.path_relevant and self.small_text_candidate


@dataclass(frozen=True)
class GeneratedFileDecision:
    observation: GeneratedFileObservation
    is_relevant: bool
    is_ignored: bool

    @property
    def should_include(self) -> bool:
        return self.is_relevant and not self.is_ignored


@dataclass(frozen=True)
class GeneratedArtifactCopyPlan:
    root_name: str
    source_relative: Path
    destination_relative: Path


class GeneratedFileExpectationLike(Protocol):
    relative_substrings: tuple[str, ...]
    text_suffixes: tuple[str, ...]
    content_markers: tuple[str, ...]
    include_user_content_sentinel: bool
    max_text_bytes: int


def is_excluded_generated_path(relative: Path, excludes: Iterable[str]) -> bool:
    excluded_parts = set(excludes)
    return any(part in excluded_parts for part in relative.parts)


def is_expected_generated_key(expected: Iterable[InstallSurface], root_name: str, relative: Path) -> bool:
    return any(surface.root == root_name and surface.relative == relative.as_posix() for surface in expected)


def is_skill_sidecar_relative(expected: Iterable[InstallSurface], root_name: str, relative: Path) -> bool:
    for surface in expected:
        if root_name != surface.root or not is_skill_effect(surface):
            continue
        if relative == skill_version_relative(surface):
            return True
        for sidecar_dir in (skill_references_relative(surface), skill_references_tmp_relative(surface)):
            try:
                relative.relative_to(sidecar_dir)
                return True
            except ValueError:
                pass
    return False


def is_small_text_candidate(expectation: GeneratedFileExpectationLike, *, file_size: int, suffix: str) -> bool:
    if file_size > expectation.max_text_bytes:
        return False
    return suffix in expectation.text_suffixes


def text_mentions_expected_generated_marker(expectation: GeneratedFileExpectationLike, text: str) -> bool:
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in expectation.content_markers):
        return True
    return expectation.include_user_content_sentinel and USER_SENTINEL in text


def generated_file_observation(
    expectation: GeneratedFileExpectationLike,
    expected: Iterable[InstallSurface],
    root_name: str,
    relative: Path,
    *,
    file_size: int | None,
    mentions_expected_marker: bool,
    excluded_path: bool,
    expected_keys: AbstractSet[tuple[str, str]] | None = None,
) -> GeneratedFileObservation:
    rel = relative.as_posix()
    return GeneratedFileObservation(
        root_name=root_name,
        relative=relative,
        suffix=relative.suffix,
        file_size=file_size,
        mentions_expected_marker=mentions_expected_marker,
        expected_key=(
            (root_name, rel) in expected_keys
            if expected_keys is not None
            else is_expected_generated_key(expected, root_name, relative)
        ),
        skill_sidecar_relative=is_skill_sidecar_relative(expected, root_name, relative),
        excluded_path=excluded_path,
        relative_substring_match=any(fragment.lower() in rel.lower() for fragment in expectation.relative_substrings),
        small_text_candidate=file_size is not None and is_small_text_candidate(expectation, file_size=file_size, suffix=relative.suffix),
    )


def decide_generated_file_observation(observation: GeneratedFileObservation) -> GeneratedFileDecision:
    relevant = observation.path_relevant or (observation.small_text_candidate and observation.mentions_expected_marker)
    return GeneratedFileDecision(
        observation=observation,
        is_relevant=relevant,
        is_ignored=observation.excluded_path,
    )


def generated_artifact_copy_plan(root_name: str, source_relative: Path) -> GeneratedArtifactCopyPlan:
    return GeneratedArtifactCopyPlan(
        root_name=root_name,
        source_relative=source_relative,
        destination_relative=Path(root_name) / source_relative,
    )


def is_relevant_generated_file(
    expectation: GeneratedFileExpectationLike,
    expected: Iterable[InstallSurface],
    root_name: str,
    relative: Path,
    *,
    small_text_candidate: bool,
    mentions_expected_marker: bool,
) -> bool:
    rel = relative.as_posix()
    observation = GeneratedFileObservation(
        root_name=root_name,
        relative=relative,
        suffix=relative.suffix,
        file_size=0 if small_text_candidate else None,
        mentions_expected_marker=mentions_expected_marker,
        expected_key=is_expected_generated_key(expected, root_name, relative),
        skill_sidecar_relative=is_skill_sidecar_relative(expected, root_name, relative),
        excluded_path=False,
        relative_substring_match=any(fragment.lower() in rel.lower() for fragment in expectation.relative_substrings),
        small_text_candidate=small_text_candidate,
    )
    return decide_generated_file_observation(observation).is_relevant
