from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable, Mapping

try:
    from ..file_walk import pruned_file_walk as walk_pruned_files
    from ..install_surface_generated import (
        GeneratedFileDecision,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        text_mentions_expected_generated_marker,
    )
    from ..install_surface_state import expected_generated_relative_keys
    from ..platform_specs import Scenario
    from ..reference_resolution import PackagedReferenceResolution
except ImportError:  # pragma: no cover - direct script import fallback
    from file_walk import pruned_file_walk as walk_pruned_files  # type: ignore[no-redef]
    from install_surface_generated import (  # type: ignore[no-redef]
        GeneratedFileDecision,
        decide_generated_file_observation,
        generated_artifact_copy_plan,
        generated_file_observation,
        is_excluded_generated_path,
        text_mentions_expected_generated_marker,
    )
    from install_surface_state import expected_generated_relative_keys  # type: ignore[no-redef]
    from platform_specs import Scenario  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution  # type: ignore[no-redef]


GENERATED_COPY_EXCLUDES = (
    ".local",
    ".cache",
    "__pycache__",
    ".pytest_cache",
)


def _check_record(
    path: Path | str,
    ok: bool,
    detail: str,
    *,
    root: str | None = None,
    relative: str | Path | None = None,
    **extra: object,
) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


def pruned_file_walk(base: Path, manifest_prune_dirs: set[str]) -> Iterable[Path]:
    yield from walk_pruned_files(base, manifest_prune_dirs)


def file_mentions_expected_generated_marker(scenario: Scenario, path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return text_mentions_expected_generated_marker(scenario.generated_file_expectation, text)


def generated_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def generated_file_decision(
    scenario: Scenario,
    root_name: str,
    relative: Path,
    path: Path,
    *,
    apply_excludes: bool,
    generated_copy_excludes: Iterable[str] = GENERATED_COPY_EXCLUDES,
    expected_keys: set[tuple[str, str]] | None = None,
    size_for_path: Callable[[Path], int | None] = generated_file_size,
    marker_match_for_path: Callable[[Scenario, Path], bool] = file_mentions_expected_generated_marker,
) -> GeneratedFileDecision:
    excluded_path = apply_excludes and is_excluded_generated_path(relative, generated_copy_excludes)
    size = None if excluded_path else size_for_path(path)
    observation = generated_file_observation(
        scenario.generated_file_expectation,
        scenario.expected,
        root_name,
        relative,
        file_size=size,
        mentions_expected_marker=False,
        excluded_path=excluded_path,
        expected_keys=expected_keys,
    )
    if observation.needs_text_marker_match:
        observation = generated_file_observation(
            scenario.generated_file_expectation,
            scenario.expected,
            root_name,
            relative,
            file_size=size,
            mentions_expected_marker=marker_match_for_path(scenario, path),
            excluded_path=excluded_path,
            expected_keys=expected_keys,
        )
    return decide_generated_file_observation(observation)


def is_relevant_generated_file(
    scenario: Scenario,
    root_name: str,
    relative: Path,
    path: Path,
    generated_file_decision_for: Callable[..., GeneratedFileDecision] = generated_file_decision,
) -> bool:
    return generated_file_decision_for(scenario, root_name, relative, path, apply_excludes=False).is_relevant


def assert_no_unexpected_graphify_files(
    scenario: Scenario,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
    *,
    phase: str,
    expected_keys: set[tuple[str, str]] | None = None,
    pruned_file_walk_for: Callable[[Path], Iterable[Path]],
    generated_file_decision_for: Callable[..., GeneratedFileDecision],
) -> list[dict[str, object]]:
    expected = (
        expected_generated_relative_keys(
            scenario.expected,
            packaged_reference_resolution(scenario.platform),
        )
        if expected_keys is None
        else expected_keys
    )
    checks: list[dict[str, object]] = []
    for root_name, root in roots.items():
        if not root.exists():
            continue
        for path in pruned_file_walk_for(root):
            relative = path.relative_to(root)
            rel = relative.as_posix()
            decision = generated_file_decision_for(
                scenario,
                root_name,
                relative,
                path,
                apply_excludes=True,
                expected_keys=expected,
            )
            if decision.observation.expected_key:
                continue
            if not decision.should_include:
                continue
            checks.append(
                _check_record(
                    path,
                    False,
                    f"unexpected_graphify_related_file_after_{phase}",
                    root=root_name,
                    relative=rel,
                )
            )
    if not checks:
        checks.append(_check_record("unexpected-graphify-files", True, f"none_after_{phase}"))
    return checks


def copy_generated_files(
    scenario: Scenario,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
    artifact_dir: Path,
    *,
    pruned_file_walk_for: Callable[[Path], Iterable[Path]],
    generated_file_decision_for: Callable[..., GeneratedFileDecision],
) -> None:
    out = artifact_dir / "generated-files"
    if out.exists():
        shutil.rmtree(out)
    expected_keys = expected_generated_relative_keys(
        scenario.expected,
        packaged_reference_resolution(scenario.platform),
    )
    for root_name, root in roots.items():
        if not root.exists():
            continue
        for path in pruned_file_walk_for(root):
            rel = path.relative_to(root)
            if not generated_file_decision_for(
                scenario,
                root_name,
                rel,
                path,
                apply_excludes=True,
                expected_keys=expected_keys,
            ).should_include:
                continue
            plan = generated_artifact_copy_plan(root_name, rel)
            dest = out / plan.destination_relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
