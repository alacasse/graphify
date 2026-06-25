from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

try:
    from ..surfaces.install_surface_models import InstallSurface, TextExpectation, is_skill_effect
    from ..surfaces.install_surface_state import (
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        expected_generated_relative_keys,
        expected_manifest_relatives,
        idempotency_state_changes,
        planned_state_entries,
        user_content_seed_plans,
    )
    from ..targets.install_target_models import Scenario
    from ..reference_resolution import PackagedReferenceResolution
except ImportError:  # pragma: no cover - direct script import fallback
    from surfaces.install_surface_models import InstallSurface, TextExpectation, is_skill_effect  # type: ignore[no-redef]
    from surfaces.install_surface_state import (  # type: ignore[no-redef]
        STALE_GRAPHIFY_SENTINEL,
        USER_SENTINEL,
        expected_generated_relative_keys,
        expected_manifest_relatives,
        idempotency_state_changes,
        planned_state_entries,
        user_content_seed_plans,
    )
    from targets.install_target_models import Scenario  # type: ignore[no-redef]
    from reference_resolution import PackagedReferenceResolution  # type: ignore[no-redef]


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


def seed_user_owned_content(
    scenario: Scenario,
    root_path_for: Callable[[str], Path],
) -> None:
    for plan in user_content_seed_plans(scenario.expected):
        path = root_path_for(plan.root_name) / plan.relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.text, encoding="utf-8")


def scenario_file_state(
    scenario: Scenario,
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution],
    root_path_for: Callable[[str], Path],
    installed_skill_reference_relatives_for: Callable[[InstallSurface], set[Path]],
    file_fingerprint_for: Callable[[Path, str | None, TextExpectation | None], dict[str, object]],
) -> dict[str, dict[str, object]]:
    state: dict[str, dict[str, object]] = {}
    installed_reference_relatives = {
        (entry.root, entry.relative): installed_skill_reference_relatives_for(entry)
        for entry in scenario.expected
        if is_skill_effect(entry)
    }
    plan = planned_state_entries(
        scenario.expected,
        packaged_reference_resolution(scenario.platform),
        installed_skill_reference_relatives=installed_reference_relatives,
    )
    for entry in plan:
        state[entry.key] = file_fingerprint_for(
            root_path_for(entry.root_name) / entry.relative,
            entry.marker,
            entry.text_expectation,
        )
    return state


def assert_idempotent_state(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for change in idempotency_state_changes(before, after):
        checks.append(
            _check_record(
                change.key,
                change.stable,
                "unchanged_after_repeat_install" if change.stable else "changed_after_repeat_install",
            )
        )
    return checks
