from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

try:
    from .expected_effects import is_json_effect
    from .install_surface_core import resolve_install_surface_path
    from .install_surface_statuses import (
        FileFingerprintObservation,
        InstallSurfaceObservation,
        UninstallSurfaceObservation,
        file_fingerprint_from_observation,
        install_surface_kind_status_from_observation,
        installed_surface_status_from_observation,
        uninstalled_surface_status_from_observation,
    )
    from .platform_specs import InstallSurface, Scenario, TextExpectation
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import is_json_effect  # type: ignore[no-redef]
    from install_surface_core import resolve_install_surface_path  # type: ignore[no-redef]
    from install_surface_statuses import (  # type: ignore[no-redef]
        FileFingerprintObservation,
        InstallSurfaceObservation,
        UninstallSurfaceObservation,
        file_fingerprint_from_observation,
        install_surface_kind_status_from_observation,
        installed_surface_status_from_observation,
        uninstalled_surface_status_from_observation,
    )
    from platform_specs import InstallSurface, Scenario, TextExpectation  # type: ignore[no-redef]


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


def installed_surface_observation(entry: InstallSurface, roots: Mapping[str, Path]) -> InstallSurfaceObservation:
    path = resolve_install_surface_path(entry, roots)
    base = InstallSurfaceObservation(
        path=path,
        exists=path.exists(),
        is_file=path.is_file(),
        is_dir=path.is_dir(),
    )
    status = install_surface_kind_status_from_observation(entry, base)
    if not status.ok or not entry.marker:
        return base
    if is_json_effect(entry):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return InstallSurfaceObservation(
                path=path,
                exists=base.exists,
                is_file=base.is_file,
                is_dir=base.is_dir,
                json_error_detail=f"invalid_json={exc.msg}",
            )
        except OSError as exc:
            return InstallSurfaceObservation(
                path=path,
                exists=base.exists,
                is_file=base.is_file,
                is_dir=base.is_dir,
                json_error_detail=f"json_read_failed={exc}",
            )
        return InstallSurfaceObservation(
            path=path,
            exists=base.exists,
            is_file=base.is_file,
            is_dir=base.is_dir,
            json_data=data,
            json_loaded=True,
        )
    return InstallSurfaceObservation(
        path=path,
        exists=base.exists,
        is_file=base.is_file,
        is_dir=base.is_dir,
        text=path.read_text(encoding="utf-8", errors="replace"),
    )


def expected_entry_status(entry: InstallSurface, roots: Mapping[str, Path]) -> tuple[bool, str]:
    return expected_entry_status_from_observation(entry, installed_surface_observation(entry, roots))


def expected_entry_status_from_observation(entry: InstallSurface, observation: InstallSurfaceObservation) -> tuple[bool, str]:
    status = installed_surface_status_from_observation(entry, observation)
    return status.ok, status.detail


def assert_expected_files(
    scenario: Scenario,
    roots: Mapping[str, Path],
    installed_skill_sidecar_checks: Callable[[Scenario, InstallSurface], list[dict[str, object]]],
    expected_entry_status_for: Callable[[InstallSurface], tuple[bool, str]] | None = None,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = resolve_install_surface_path(entry, roots)
        ok, detail = (
            expected_entry_status(entry, roots)
            if expected_entry_status_for is None
            else expected_entry_status_for(entry)
        )
        checks.append(_check_record(path, ok, detail, root=entry.root, relative=entry.relative))
        checks.extend(installed_skill_sidecar_checks(scenario, entry))
    return checks


def uninstalled_surface_observation(entry: InstallSurface, roots: Mapping[str, Path]) -> UninstallSurfaceObservation:
    path = resolve_install_surface_path(entry, roots)
    base = UninstallSurfaceObservation(
        path=path,
        exists=path.exists(),
        is_file=path.is_file(),
        is_dir=path.is_dir(),
    )
    text_expectation = entry.text_expectation
    if entry.marker and text_expectation.require_user_content_on_uninstall:
        if not (base.exists and base.is_file):
            return base
    elif not (entry.marker and text_expectation.remove_graphify_section_on_uninstall and base.exists):
        return base
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return UninstallSurfaceObservation(
            path=path,
            exists=base.exists,
            is_file=base.is_file,
            is_dir=base.is_dir,
            text_error_detail=f"text_read_failed={exc}",
        )
    return UninstallSurfaceObservation(
        path=path,
        exists=base.exists,
        is_file=base.is_file,
        is_dir=base.is_dir,
        text=text,
    )


def uninstalled_entry_status(entry: InstallSurface, roots: Mapping[str, Path]) -> tuple[bool, str]:
    return uninstalled_entry_status_from_observation(entry, uninstalled_surface_observation(entry, roots))


def uninstalled_entry_status_from_observation(entry: InstallSurface, observation: UninstallSurfaceObservation) -> tuple[bool, str]:
    status = uninstalled_surface_status_from_observation(entry, observation)
    return status.ok, status.detail


def assert_uninstalled(
    scenario: Scenario,
    roots: Mapping[str, Path],
    uninstalled_skill_sidecar_checks: Callable[[InstallSurface], list[dict[str, object]]],
    uninstalled_entry_status_for: Callable[[InstallSurface], tuple[bool, str]] | None = None,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        path = resolve_install_surface_path(entry, roots)
        if not entry.remove_on_uninstall:
            continue
        ok, detail = (
            uninstalled_entry_status(entry, roots)
            if uninstalled_entry_status_for is None
            else uninstalled_entry_status_for(entry)
        )
        checks.append(_check_record(path, ok, detail, root=entry.root, relative=entry.relative))
        checks.extend(uninstalled_skill_sidecar_checks(entry))
    return checks


def assert_scope_boundaries(scenario: Scenario, roots: Mapping[str, Path]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for entry in scenario.expected:
        allowed = not scenario.allowed_roots or entry.root in scenario.allowed_roots
        checks.append(
            _check_record(
                resolve_install_surface_path(entry, roots),
                allowed,
                "allowed_root" if allowed else "unexpected_root",
            )
        )
    return checks


def file_fingerprint(
    path: Path,
    marker: str | None = None,
    text_expectation: TextExpectation | None = None,
) -> dict[str, object]:
    if not path.exists():
        observation = FileFingerprintObservation(exists=False)
    elif path.is_dir():
        observation = FileFingerprintObservation(exists=True, kind="dir")
    else:
        data = path.read_bytes()
        observation = FileFingerprintObservation(
            exists=True,
            kind="file",
            data=data,
            text=data.decode("utf-8", errors="replace") if marker else None,
        )
    return file_fingerprint_from_observation(observation, marker, text_expectation)
