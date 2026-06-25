from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

try:
    from ..surfaces.install_surface_models import InstallSurface, is_skill_effect
    from ..surfaces.install_surface_sidecars import (
        expected_skill_sidecar_relatives,
        installed_reference_sidecar_status,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_sidecar_expectation,
        skill_version_relative,
        skill_version_status,
        uninstalled_skill_sidecar_status,
    )
    from ..surfaces.install_surface_state import stale_sidecar_seed_plans
    from ..targets.install_target_models import Scenario
    from ..reference_resolution import PackagedReferenceResolution
except ImportError:  # pragma: no cover - direct script import fallback
    from surfaces.install_surface_models import InstallSurface, is_skill_effect  # type: ignore[no-redef]
    from surfaces.install_surface_sidecars import (  # type: ignore[no-redef]
        expected_skill_sidecar_relatives,
        installed_reference_sidecar_status,
        reference_sidecar_expectation,
        references_tmp_absence_status,
        skill_dir_for_entry,
        skill_reference_pointer_status,
        skill_references_relative,
        skill_references_tmp_relative,
        skill_sidecar_expectation,
        skill_version_relative,
        skill_version_status,
        uninstalled_skill_sidecar_status,
    )
    from surfaces.install_surface_state import stale_sidecar_seed_plans  # type: ignore[no-redef]
    from targets.install_target_models import Scenario  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution  # type: ignore[no-redef]


STALE_SIDECAR_SEED_DETAILS = {
    "stale_reference_fragment": "seeded_stale_reference_fragment",
    "staged_reference_fragment": "seeded_staged_reference_fragment",
}


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


def _root_path(root_name: str, roots: Mapping[str, Path]) -> Path:
    try:
        return roots[root_name]
    except KeyError as exc:
        raise AssertionError(f"unknown root: {root_name}") from exc


def skill_assertion_record(
    entry: InstallSurface,
    roots: Mapping[str, Path],
    relative: Path,
    ok: bool,
    detail: str,
) -> dict[str, object]:
    return _check_record(_root_path(entry.root, roots) / relative, ok, detail, root=entry.root, relative=relative)


def installed_reference_names(refs_dir: Path) -> list[str]:
    if not refs_dir.is_dir():
        return []
    return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())


def installed_skill_reference_relatives(entry: InstallSurface, roots: Mapping[str, Path]) -> set[Path]:
    refs_dir = skill_dir_for_entry(entry, roots) / skill_sidecar_expectation(entry).references_dir
    refs_relative = skill_references_relative(entry)
    if not refs_dir.is_dir():
        return set()
    return {refs_relative / path.name for path in refs_dir.glob("*.md") if path.is_file()}


def tracked_skill_sidecar_relatives(
    scenario: Scenario,
    entry: InstallSurface,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
) -> set[Path]:
    return expected_skill_sidecar_relatives(entry, packaged_reference_resolution(scenario.platform)) | installed_skill_reference_relatives(entry, roots)


def check_skill_version(
    entry: InstallSurface,
    roots: Mapping[str, Path],
    expected_graphify_version: Callable[[], str],
) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry, roots)
    version_path = skill_dir / skill_sidecar_expectation(entry).version_name
    version_relative = skill_version_relative(entry)
    expected_version = expected_graphify_version()
    version_text = version_path.read_text(encoding="utf-8", errors="replace") if version_path.exists() else None
    version_ok, version_detail = skill_version_status(version_text, expected_version)
    return skill_assertion_record(entry, roots, version_relative, version_ok, version_detail)


def check_references_tmp_absent(entry: InstallSurface, roots: Mapping[str, Path]) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry, roots)
    refs_tmp = skill_dir / skill_sidecar_expectation(entry).references_tmp_dir
    tmp_ok, tmp_detail = references_tmp_absence_status(refs_tmp.exists())
    return skill_assertion_record(
        entry,
        roots,
        skill_references_tmp_relative(entry),
        tmp_ok,
        tmp_detail,
    )


def check_packaged_references(
    scenario: Scenario,
    entry: InstallSurface,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
) -> dict[str, object]:
    skill_dir = skill_dir_for_entry(entry, roots)
    refs_dir = skill_dir / skill_sidecar_expectation(entry).references_dir
    refs_relative = skill_references_relative(entry)
    expectation = reference_sidecar_expectation(packaged_reference_resolution(scenario.platform))
    refs_ok, refs_detail = installed_reference_sidecar_status(
        expectation,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    return skill_assertion_record(entry, roots, refs_relative, refs_ok, refs_detail)


def check_skill_reference_pointers(
    entry: InstallSurface,
    roots: Mapping[str, Path],
    skill_text: str,
) -> dict[str, object]:
    sidecar = skill_sidecar_expectation(entry)
    refs_dir = skill_dir_for_entry(entry, roots) / sidecar.references_dir
    pointer_ok, pointer_detail = skill_reference_pointer_status(
        sidecar,
        skill_text,
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    return skill_assertion_record(entry, roots, Path(entry.relative), pointer_ok, pointer_detail)


def assert_installed_skill_sidecar(
    scenario: Scenario,
    entry: InstallSurface,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
    expected_graphify_version: Callable[[], str],
) -> list[dict[str, object]]:
    if not is_skill_effect(entry):
        return []

    skill_path = _root_path(entry.root, roots) / entry.relative
    skill_text = skill_path.read_text(encoding="utf-8", errors="replace") if skill_path.is_file() else ""
    return [
        check_skill_version(entry, roots, expected_graphify_version),
        check_references_tmp_absent(entry, roots),
        check_packaged_references(scenario, entry, roots, packaged_reference_resolution),
        check_skill_reference_pointers(entry, roots, skill_text),
    ]


def assert_installed_skill_sidecars(
    scenario: Scenario,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
    expected_graphify_version: Callable[[], str],
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        checks.extend(assert_installed_skill_sidecar(scenario, entry, roots, packaged_reference_resolution, expected_graphify_version))
    return checks


def seed_stale_skill_sidecars(
    scenario: Scenario,
    roots: Mapping[str, Path],
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
) -> list[dict[str, object]]:
    seeded: list[dict[str, object]] = []
    plans = stale_sidecar_seed_plans(
        scenario.expected,
        packaged_reference_resolution(scenario.platform),
    )
    for plan in plans:
        path = _root_path(plan.root_name, roots) / plan.relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.text, encoding="utf-8")
        seeded.append(
            _check_record(
                path,
                True,
                STALE_SIDECAR_SEED_DETAILS[plan.kind],
                root=plan.root_name,
                relative=plan.relative,
            )
        )
    return seeded


def uninstalled_skill_sidecar_checks(
    entry: InstallSurface,
    roots: Mapping[str, Path],
) -> list[dict[str, object]]:
    if not is_skill_effect(entry):
        return []
    checks: list[dict[str, object]] = []
    for relative in (skill_version_relative(entry), skill_references_relative(entry), skill_references_tmp_relative(entry)):
        sidecar_path = _root_path(entry.root, roots) / relative
        sidecar_ok, sidecar_detail = uninstalled_skill_sidecar_status(sidecar_path.exists())
        checks.append(
            _check_record(
                sidecar_path,
                sidecar_ok,
                sidecar_detail,
                root=entry.root,
                relative=relative,
            )
        )
    return checks
