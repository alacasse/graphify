from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.install_sandbox.effects import file_effect_generated_artifacts
from tools.install_sandbox.effects import file_effect_oracle
from tools.install_sandbox.effects import file_effect_state
from tools.install_sandbox.effects import file_effect_surfaces
from tools.install_sandbox.surfaces import install_surface_statuses
from tools.install_sandbox.surfaces import path_resolution
from tools.install_sandbox.targets.reference_resolution import PackagedReferenceResolution
from tools.install_sandbox.targets import install_target_models
from tools.install_sandbox.targets.install_target_models import ExpectedPath, InstallSurface, Scenario


@pytest.fixture
def roots(tmp_path) -> dict[str, Path]:
    paths = {"home": tmp_path / "home", "project": tmp_path / "project", "user_cwd": tmp_path / "user-cwd"}
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


@pytest.fixture
def oracle(roots) -> file_effect_oracle.FileEffectOracle:
    def packaged_reference_resolution(platform: str) -> PackagedReferenceResolution:
        if platform == "claude":
            return resolution("available", ("query.md", "update.md"), "claude refs")
        if platform == "empty":
            return resolution("empty", detail="empty refs")
        if platform == "no_eligible":
            return resolution("no_eligible_bundle", detail="no eligible refs")
        if platform == "missing":
            return resolution("missing", detail="missing /package/refs")
        if platform == "not_directory":
            return resolution("not_directory", detail="not_directory /package/refs")
        return resolution("intentionally_absent", detail="absent refs")

    return file_effect_oracle.FileEffectOracle(
        roots=roots,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=lambda: "9.9.9",
        manifest_prune_dirs=set(file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES),
    )


def scenario(platform: str, *expected: InstallSurface, scope: str = "project") -> Scenario:
    return Scenario(
        target_name=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
    )


def section(root: str, relative: str, marker: str = install_target_models.GRAPHIFY_MARKER, *, preserve_user_content: bool = False) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        marker=marker,
        text_expectation=install_target_models.TextExpectation(
            preserve_user_content=preserve_user_content,
            repair_stale_graphify_section=True,
            require_user_content_on_uninstall=preserve_user_content,
        ),
    )


def write_skill(root: Path, relative: str, *, body: str = "# graphify skill\n", version: str | None = None) -> Path:
    skill = root / relative
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(body, encoding="utf-8")
    if version is not None:
        (skill.parent / ".graphify_version").write_text(version, encoding="utf-8")
    return skill


def check_by_relative(checks: list[dict[str, object]], relative: str) -> dict[str, object]:
    return next(check for check in checks if check.get("relative") == relative)


def test_file_effect_surfaces_file_fingerprint_observes_paths_and_delegates_to_core(tmp_path: Path) -> None:
    marker = "## graphify"
    text_expectation = install_target_models.TextExpectation(preserve_user_content=True, repair_stale_graphify_section=True)
    missing = tmp_path / "missing.md"
    assert file_effect_surfaces.file_fingerprint(missing) == install_surface_statuses.file_fingerprint_from_observation(
        install_surface_statuses.FileFingerprintObservation(exists=False)
    )

    directory = tmp_path / "notes-dir"
    directory.mkdir()
    assert file_effect_surfaces.file_fingerprint(directory) == install_surface_statuses.file_fingerprint_from_observation(
        install_surface_statuses.FileFingerprintObservation(exists=True, kind="dir")
    )

    text = f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n{marker}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n"
    path = tmp_path / "notes.md"
    path.write_text(text, encoding="utf-8")
    data = text.encode("utf-8")

    assert file_effect_surfaces.file_fingerprint(path, marker, text_expectation) == install_surface_statuses.file_fingerprint_from_observation(
        install_surface_statuses.FileFingerprintObservation(
            exists=True,
            kind="file",
            data=data,
            text=text,
        ),
        marker,
        text_expectation,
    )


def test_assertion_detects_missing_file(oracle) -> None:
    checks = oracle.assert_expected_files(scenario("unit", ExpectedPath("project", "missing.txt")))

    assert len(checks) == 1
    assert checks[0]["ok"] is False
    assert checks[0]["detail"] == "missing"


def test_install_surface_alias_is_accepted_by_scenario_and_oracle(oracle, roots) -> None:
    assert install_target_models.ExpectedPath is install_target_models.InstallSurface

    surface = install_target_models.InstallSurface("project", "surface.txt")
    (roots["project"] / "surface.txt").write_text("installed\n", encoding="utf-8")
    test_scenario = Scenario(
        target_name="unit",
        scope="project",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project",
        expected=(surface,),
    )

    checks = oracle.assert_expected_files(test_scenario)

    assert test_scenario.expected == (surface,)
    assert checks == [
        {
            "path": str(roots["project"] / "surface.txt"),
            "ok": True,
            "detail": "file",
            "root": "project",
            "relative": "surface.txt",
        }
    ]


def test_install_surface_path_uses_declared_root_and_relative(oracle, roots) -> None:
    surface = InstallSurface("project", "nested/surface.txt")

    assert path_resolution.resolve_install_root("home", roots) == roots["home"]
    assert path_resolution.resolve_install_surface_path(surface, roots) == roots["project"] / "nested/surface.txt"

    with pytest.raises(AssertionError, match="unknown root: missing"):
        path_resolution.resolve_install_surface_path(InstallSurface("missing", "surface.txt"), roots)


def test_install_surface_kind_status_contracts(oracle, roots) -> None:
    file_surface = InstallSurface("project", "installed.txt")
    dir_surface = InstallSurface("project", "installed-dir", kind="dir")
    generic_surface = InstallSurface("project", "socketish", kind="exists")
    wrong_dir_surface = InstallSurface("project", "wrong-dir", kind="dir")

    (roots["project"] / "installed.txt").write_text("installed\n", encoding="utf-8")
    (roots["project"] / "installed-dir").mkdir()
    (roots["project"] / "socketish").write_text("installed\n", encoding="utf-8")
    (roots["project"] / "wrong-dir").write_text("not a directory\n", encoding="utf-8")

    assert file_effect_surfaces.expected_entry_status(file_surface, roots) == (True, "file")
    assert file_effect_surfaces.expected_entry_status(dir_surface, roots) == (True, "directory")
    assert file_effect_surfaces.expected_entry_status(generic_surface, roots) == (True, "exists")
    assert file_effect_surfaces.expected_entry_status(wrong_dir_surface, roots) == (False, "expected_directory_but_not_directory")
    assert file_effect_surfaces.expected_entry_status(InstallSurface("project", "missing-dir", kind="dir"), roots) == (False, "missing")


def test_assert_expected_files_uses_surface_module_installed_surface_observation(oracle, roots, monkeypatch) -> None:
    surface = section("project", "virtual-notes.md", preserve_user_content=True)
    path = roots["project"] / "virtual-notes.md"
    observed_text = f"{file_effect_state.USER_SENTINEL}\n\n{install_target_models.GRAPHIFY_MARKER}\nnew section\n"
    observed = install_surface_statuses.InstallSurfaceObservation(
        path=path,
        exists=True,
        is_file=True,
        text=observed_text,
    )
    calls: list[InstallSurface] = []

    def installed_surface_observation(entry: InstallSurface, observed_roots: dict[str, Path]) -> install_surface_statuses.InstallSurfaceObservation:
        calls.append(entry)
        assert observed_roots is roots
        return observed

    monkeypatch.setattr(file_effect_surfaces, "installed_surface_observation", installed_surface_observation)

    checks = oracle.assert_expected_files(scenario("unit", surface))

    assert calls == [surface]
    assert not path.exists()
    assert checks == [
        {
            "path": str(path),
            "ok": True,
            "detail": "marker_count=1; user_content_preserved; stale_replaced=True",
            "root": "project",
            "relative": "virtual-notes.md",
        }
    ]


def test_surface_owner_routes_installed_surface_observation_to_core(oracle, roots, monkeypatch) -> None:
    surface = section("project", "notes.md", preserve_user_content=True)
    path = roots["project"] / "notes.md"
    text = f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n{install_target_models.GRAPHIFY_MARKER}\nnew section\n"
    path.write_text(text, encoding="utf-8")
    captured: dict[str, object] = {}

    def decide_from_observation(entry, observation):
        captured["entry"] = entry
        captured["observation"] = observation
        return install_surface_statuses.InstallSurfaceStatus(observation.path, True, "observed_by_core")

    monkeypatch.setattr(file_effect_surfaces, "installed_surface_status_from_observation", decide_from_observation)

    assert file_effect_surfaces.expected_entry_status(surface, roots) == (True, "observed_by_core")
    assert captured["entry"] is surface
    observation = captured["observation"]
    assert isinstance(observation, install_surface_statuses.InstallSurfaceObservation)
    assert observation.path == path
    assert observation.exists is True
    assert observation.is_file is True
    assert observation.text == text


def test_oracle_renders_installed_surface_observations_as_assertion_records(oracle, roots) -> None:
    missing = InstallSurface("project", "missing.txt")
    wrong_kind = InstallSurface("project", "wrong-kind", kind="dir")
    text_surface = section("project", "notes.md", preserve_user_content=True)
    registered_json = InstallSurface(
        "project",
        "hooks.json",
        content_kind="json",
        marker="graphify",
        json_expectation=install_target_models.JsonExpectation(
            schema_name="unit_hooks",
            hooks=(install_target_models.JsonHookExpectation("PreToolUse", "Bash", "bash_hook_present"),),
        ),
    )
    (roots["project"] / "wrong-kind").write_text("not a directory\n", encoding="utf-8")
    (roots["project"] / "notes.md").write_text(
        f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n"
        f"{install_target_models.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    (roots["project"] / "hooks.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}),
        encoding="utf-8",
    )
    test_scenario = scenario("unit", missing, wrong_kind, text_surface, registered_json)

    decisions = [
        file_effect_surfaces.installed_surface_status_from_observation(
            surface,
            file_effect_surfaces.installed_surface_observation(surface, roots),
        )
        for surface in test_scenario.expected
    ]
    checks = oracle.assert_expected_files(test_scenario)

    assert [(decision.ok, decision.detail) for decision in decisions] == [
        (False, "missing"),
        (False, "expected_directory_but_not_directory"),
        (False, "marker_count=1; user_content_preserved; stale_replaced=False"),
        (False, "valid_json=true; schema=unit_hooks; bash_hook_present=False"),
    ]
    assert checks == [
        {
            "path": str(roots["project"] / "missing.txt"),
            "ok": False,
            "detail": "missing",
            "root": "project",
            "relative": "missing.txt",
        },
        {
            "path": str(roots["project"] / "wrong-kind"),
            "ok": False,
            "detail": "expected_directory_but_not_directory",
            "root": "project",
            "relative": "wrong-kind",
        },
        {
            "path": str(roots["project"] / "notes.md"),
            "ok": False,
            "detail": "marker_count=1; user_content_preserved; stale_replaced=False",
            "root": "project",
            "relative": "notes.md",
        },
        {
            "path": str(roots["project"] / "hooks.json"),
            "ok": False,
            "detail": "valid_json=true; schema=unit_hooks; bash_hook_present=False",
            "root": "project",
            "relative": "hooks.json",
        },
    ]


def test_uninstall_surface_status_contracts(oracle, roots) -> None:
    plain = InstallSurface("project", "plain.txt")
    plain_path = roots["project"] / "plain.txt"

    assert file_effect_surfaces.uninstalled_entry_status(plain, roots) == (True, "removed")

    plain_path.write_text("still here\n", encoding="utf-8")
    assert file_effect_surfaces.uninstalled_entry_status(plain, roots) == (False, "still_exists")

    text_section = section("project", "notes.md", preserve_user_content=True)
    notes_path = roots["project"] / "notes.md"
    notes_path.write_text(f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n## User Section\n", encoding="utf-8")
    assert file_effect_surfaces.uninstalled_entry_status(text_section, roots) == (True, "graphify_removed=True; user_content_preserved=True")

    notes_path.write_text(
        f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n{install_target_models.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    assert file_effect_surfaces.uninstalled_entry_status(text_section, roots) == (False, "graphify_removed=False; user_content_preserved=True")


def test_assert_uninstalled_uses_surface_module_uninstalled_surface_observation(oracle, roots, monkeypatch) -> None:
    surface = section("project", "virtual-notes.md", preserve_user_content=True)
    path = roots["project"] / "virtual-notes.md"
    observed = install_surface_statuses.UninstallSurfaceObservation(
        path=path,
        exists=True,
        is_file=True,
        text=f"{file_effect_state.USER_SENTINEL}\n\n## User Section\n",
    )
    calls: list[InstallSurface] = []

    def uninstalled_surface_observation(entry: InstallSurface, observed_roots: dict[str, Path]) -> install_surface_statuses.UninstallSurfaceObservation:
        calls.append(entry)
        assert observed_roots is roots
        return observed

    monkeypatch.setattr(file_effect_surfaces, "uninstalled_surface_observation", uninstalled_surface_observation)

    checks = oracle.assert_uninstalled(scenario("unit", surface))

    assert calls == [surface]
    assert not path.exists()
    assert checks == [
        {
            "path": str(path),
            "ok": True,
            "detail": "graphify_removed=True; user_content_preserved=True",
            "root": "project",
            "relative": "virtual-notes.md",
        }
    ]


def test_surface_owner_routes_uninstalled_surface_observation_to_core(oracle, roots, monkeypatch) -> None:
    surface = section("project", "notes.md", preserve_user_content=True)
    path = roots["project"] / "notes.md"
    text = f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n## User Section\n"
    path.write_text(text, encoding="utf-8")
    captured: dict[str, object] = {}

    def decide_from_observation(entry, observation):
        captured["entry"] = entry
        captured["observation"] = observation
        return install_surface_statuses.InstallSurfaceStatus(observation.path, True, "observed_by_core")

    monkeypatch.setattr(file_effect_surfaces, "uninstalled_surface_status_from_observation", decide_from_observation)

    assert file_effect_surfaces.uninstalled_entry_status(surface, roots) == (True, "observed_by_core")
    assert captured["entry"] is surface
    observation = captured["observation"]
    assert isinstance(observation, install_surface_statuses.UninstallSurfaceObservation)
    assert observation.path == path
    assert observation.exists is True
    assert observation.is_file is True
    assert observation.text == text


def test_oracle_renders_uninstalled_surface_observations_as_assertion_records(oracle, roots) -> None:
    plain = InstallSurface("project", "plain.txt")
    preserved_text = section("project", "notes.md", preserve_user_content=True)
    repaired_text = InstallSurface(
        "project",
        "repaired.md",
        marker=install_target_models.GRAPHIFY_MARKER,
        text_expectation=install_target_models.TextExpectation(remove_graphify_section_on_uninstall=True),
    )
    kept = InstallSurface("project", "kept.txt", remove_on_uninstall=False)
    (roots["project"] / "plain.txt").write_text("still installed\n", encoding="utf-8")
    (roots["project"] / "notes.md").write_text(
        f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n"
        f"{install_target_models.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    (roots["project"] / "repaired.md").write_text(
        f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n## User Section\n",
        encoding="utf-8",
    )
    (roots["project"] / "kept.txt").write_text("outside uninstall scope\n", encoding="utf-8")
    test_scenario = scenario("unit", plain, preserved_text, repaired_text, kept)

    decisions = [
        file_effect_surfaces.uninstalled_surface_status_from_observation(
            surface,
            file_effect_surfaces.uninstalled_surface_observation(surface, roots),
        )
        for surface in (plain, preserved_text, repaired_text)
    ]
    checks = oracle.assert_uninstalled(test_scenario)

    assert [(decision.ok, decision.detail) for decision in decisions] == [
        (False, "still_exists"),
        (False, "graphify_removed=False; user_content_preserved=True"),
        (True, "graphify_removed; user_content_preserved"),
    ]
    assert checks == [
        {
            "path": str(roots["project"] / "plain.txt"),
            "ok": False,
            "detail": "still_exists",
            "root": "project",
            "relative": "plain.txt",
        },
        {
            "path": str(roots["project"] / "notes.md"),
            "ok": False,
            "detail": "graphify_removed=False; user_content_preserved=True",
            "root": "project",
            "relative": "notes.md",
        },
        {
            "path": str(roots["project"] / "repaired.md"),
            "ok": True,
            "detail": "graphify_removed; user_content_preserved",
            "root": "project",
            "relative": "repaired.md",
        },
    ]


def test_oracle_captures_fingerprint_observations_without_assertion_record_shape(oracle, roots) -> None:
    missing = InstallSurface("project", "missing.md")
    directory = InstallSurface("project", "installed-dir", kind="dir")
    text_surface = section("project", "notes.md", preserve_user_content=True)
    (roots["project"] / "installed-dir").mkdir()
    notes_text = (
        f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n"
        f"{install_target_models.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n"
    )
    (roots["project"] / "notes.md").write_text(notes_text, encoding="utf-8")
    test_scenario = scenario("unit", missing, directory, text_surface)

    state = oracle.scenario_file_state(test_scenario)
    notes_payload = state["project/notes.md"]

    assert state["project/missing.md"] == {"exists": False}
    assert state["project/installed-dir"] == {"exists": True, "kind": "dir"}
    assert notes_payload == {
        "exists": True,
        "kind": "file",
        "sha256": hashlib.sha256(notes_text.encode("utf-8")).hexdigest(),
        "size": len(notes_text.encode("utf-8")),
        "marker_count": 1,
        "user_content_preserved": True,
        "stale_graphify_present": True,
    }
    assert not {"path", "ok", "detail"} & set(notes_payload)


def test_scenario_file_state_uses_oracle_file_fingerprint_observation_point(oracle, roots, monkeypatch) -> None:
    surface = section("project", "virtual-notes.md", preserve_user_content=True)
    path = roots["project"] / "virtual-notes.md"
    calls: list[tuple[Path, str | None, install_target_models.TextExpectation | None]] = []

    def file_fingerprint(
        self: file_effect_oracle.FileEffectOracle,
        observed_path: Path,
        marker: str | None = None,
        text_expectation: install_target_models.TextExpectation | None = None,
    ) -> dict[str, object]:
        calls.append((observed_path, marker, text_expectation))
        return {"observed": observed_path.name, "marker": marker}

    monkeypatch.setattr(file_effect_oracle.FileEffectOracle, "file_fingerprint", file_fingerprint)

    state = oracle.scenario_file_state(scenario("unit", surface))

    assert calls == [(path, install_target_models.GRAPHIFY_MARKER, surface.text_expectation)]
    assert not path.exists()
    assert state == {
        "project/virtual-notes.md": {
            "observed": "virtual-notes.md",
            "marker": install_target_models.GRAPHIFY_MARKER,
        }
    }


def test_file_effect_state_captures_planned_state_entries(roots) -> None:
    surface = section("project", "virtual-notes.md", preserve_user_content=True)
    test_scenario = scenario("unit", surface)
    calls: list[tuple[Path, str | None, install_target_models.TextExpectation | None]] = []

    def file_fingerprint(
        observed_path: Path,
        marker: str | None = None,
        text_expectation: install_target_models.TextExpectation | None = None,
    ) -> dict[str, object]:
        calls.append((observed_path, marker, text_expectation))
        return {"observed": observed_path.name, "marker": marker}

    state = file_effect_state.scenario_file_state(
        test_scenario,
        lambda platform: resolution("intentionally_absent", detail=f"{platform} refs"),
        roots.__getitem__,
        lambda entry: set(),
        file_fingerprint,
    )

    assert calls == [(roots["project"] / "virtual-notes.md", install_target_models.GRAPHIFY_MARKER, surface.text_expectation)]
    assert state == {
        "project/virtual-notes.md": {
            "observed": "virtual-notes.md",
            "marker": install_target_models.GRAPHIFY_MARKER,
        }
    }


def test_oracle_dispatches_named_effect_types(oracle, roots) -> None:
    skill = install_target_models.SkillEffect("project", ".unit/graphify/SKILL.md")
    hooks = install_target_models.JsonHooksEffect(
        "project",
        ".unit/hooks.json",
        json_expectation=install_target_models.JsonExpectation(
            schema_name="unit_hooks",
            hooks=(install_target_models.JsonHookExpectation("PreToolUse", "Bash", "bash_hook_present"),),
        ),
    )
    write_skill(roots["project"], ".unit/graphify/SKILL.md", version="9.9.9")
    hooks_path = roots["project"] / ".unit/hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "graphify hook-check"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    checks = oracle.assert_expected_files(scenario("unit", skill, hooks))

    assert all(check["ok"] for check in checks)
    assert check_by_relative(checks, ".unit/graphify/.graphify_version")["ok"] is True
    assert check_by_relative(checks, ".unit/hooks.json")["detail"] == "valid_json=true; schema=unit_hooks; bash_hook_present=True"


def test_json_marker_assertion_rejects_invalid_json(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", ".codebuddy/settings.json", content_kind="json", marker="graphify"))
    path = roots["project"] / ".codebuddy/settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"hooks": ["graphify",}', encoding="utf-8")

    check = oracle.assert_expected_files(test_scenario)[0]
    assert check["ok"] is False
    assert "invalid_json" in str(check["detail"])


def test_expected_path_kind_is_enforced(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    (roots["project"] / "AGENTS.md").mkdir()

    check = oracle.assert_expected_files(test_scenario)[0]
    assert check["ok"] is False
    assert check["detail"] == "expected_file_but_not_file"


def test_idempotency_state_detects_content_change() -> None:
    before = {
        "project/AGENTS.md": {"exists": True, "sha256": "a"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/AGENTS.md": {"exists": True, "sha256": "b"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }

    checks = file_effect_state.assert_idempotent_state(before, after)
    assert checks == [
        {"path": "project/AGENTS.md", "ok": False, "detail": "changed_after_repeat_install"},
        {"path": "project/notes.md", "ok": True, "detail": "unchanged_after_repeat_install"},
    ]
