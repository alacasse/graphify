from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools.install_sandbox import file_effects
from tools.install_sandbox import install_surface_core
from tools.install_sandbox import platform_specs
from tools.install_sandbox.platform_specs import ExpectedPath, InstallSurface, Scenario
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution

# Adapter ownership lives here. Direct Installer Core decisions belong in
# test_install_surface_core*.py; core value objects appear here only as oracle
# and ScenarioFileEffectsAdapter collaborators.


@pytest.fixture
def roots(tmp_path) -> dict[str, Path]:
    paths = {"home": tmp_path / "home", "project": tmp_path / "project", "user_cwd": tmp_path / "user-cwd"}
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


@pytest.fixture
def oracle(roots) -> file_effects.FileEffectOracle:
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

    return file_effects.FileEffectOracle(
        roots=roots,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=lambda: "9.9.9",
        manifest_prune_dirs=set(file_effects.GENERATED_COPY_EXCLUDES),
    )


def scenario(platform: str, *expected: InstallSurface, scope: str = "project") -> Scenario:
    return Scenario(
        platform=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
    )


def expected_skill(root: str, relative: str) -> InstallSurface:
    return InstallSurface(root, relative, skill_sidecar_expectation=platform_specs.SkillSidecarExpectation())


def section(root: str, relative: str, marker: str = platform_specs.GRAPHIFY_MARKER, *, preserve_user_content: bool = False) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        marker=marker,
        text_expectation=platform_specs.TextExpectation(
            preserve_user_content=preserve_user_content,
            repair_stale_graphify_section=True,
            require_user_content_on_uninstall=preserve_user_content,
        ),
    )


def test_file_effect_oracle_boundary_rejects_pure_core_pass_throughs() -> None:
    adapter_methods = {
        "root_path",
        "expected_path",
        "skill_assertion_record",
        "installed_skill_reference_relatives",
        "tracked_skill_sidecar_relatives",
        "installed_reference_names",
        "check_skill_version",
        "check_references_tmp_absent",
        "check_packaged_references",
        "check_skill_reference_pointers",
        "assert_installed_skill_sidecar",
        "assert_installed_skill_sidecars",
        "seed_stale_skill_sidecars",
        "expected_manifest_relatives",
        "seed_user_owned_content",
        "installed_surface_observation",
        "expected_entry_status",
        "assert_expected_files",
        "uninstalled_surface_observation",
        "uninstalled_entry_status",
        "uninstalled_skill_sidecar_checks",
        "assert_uninstalled",
        "pruned_file_walk",
        "assert_no_unexpected_graphify_files",
        "assert_scope_boundaries",
        "file_fingerprint",
        "scenario_file_state",
        "generated_file_size",
        "file_mentions_expected_generated_marker",
        "generated_file_decision",
        "is_relevant_generated_file",
        "copy_generated_files",
    }
    pure_core_pass_through_methods = {
        "is_skill_expected",
        "skill_sidecar_expectation",
        "skill_dir_for_entry",
        "skill_relative_dir",
        "skill_version_relative",
        "skill_references_relative",
        "skill_references_tmp_relative",
        "expected_skill_sidecar_relatives",
        "reference_sidecar_expectation",
        "skill_reference_pointers",
        "progressive_skill_entries",
        "graphify_section_removed",
        "expected_generated_relative_keys",
        "expected_generated_relative_keys_for_scenarios",
        "is_small_text_candidate",
        "is_expected_generated_key",
        "is_skill_sidecar_relative",
        "seeded_text",
        "should_exclude_generated_path",
        "should_seed_stale_graphify_section",
        "should_seed_user_content",
    }

    oracle_methods = {
        name
        for name, value in vars(file_effects.FileEffectOracle).items()
        if callable(value) and not name.startswith("_")
    }

    assert oracle_methods.isdisjoint(pure_core_pass_through_methods), (
        "FileEffectOracle should not grow pure Installer Core pass-through methods; "
        "call install_surface_core helpers directly instead."
    )
    assert oracle_methods == adapter_methods


def test_file_effects_tests_import_core_only_as_adapter_collaborator_module() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    core_test_modules = tuple(Path(__file__).parent.glob("test_install_surface_core*.py"))

    imported_core_helpers = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
    }

    assert core_test_modules, "direct Installer Core behavior tests belong in test_install_surface_core*.py"
    assert imported_core_helpers == set(), (
        "Keep test_file_effects.py adapter-owned; use module-qualified "
        "install_surface_core collaborators here and put direct core behavior tests "
        "in test_install_surface_core*.py."
    )


def test_file_effects_does_not_import_or_call_path_reading_core_wrappers() -> None:
    legacy_wrappers = {
        "expected_kind_status",
        "install_surface_kind_status",
        "json_marker_status",
        "text_marker_status",
        "installed_surface_status",
        "uninstalled_surface_status",
        "file_fingerprint",
    }
    tree = ast.parse(Path(file_effects.__file__).read_text(encoding="utf-8"))

    def dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            if parent is None:
                return None
            return f"{parent}.{node.attr}"
        return None

    imported_from_core = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
    }
    wildcard_core_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("install_surface_core")
        for alias in node.names
        if alias.name == "*"
    }
    module_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    }
    imported_core_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    core_module_aliases = {
        alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if any(part == "install_surface_core" for part in alias.name.split("."))
    } | {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module is None or node.module.endswith("install_sandbox"))
        for alias in node.names
        if alias.name == "install_surface_core"
    }
    direct_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    module_qualified_calls = {
        dotted
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in legacy_wrappers
        if (dotted := dotted_name(node.func)) is not None
        and (
            dotted.rsplit(".", maxsplit=1)[0] in core_module_aliases
            or ".install_surface_core." in dotted
        )
    }

    assert not wildcard_core_imports
    assert imported_from_core.isdisjoint(legacy_wrappers)
    assert not module_imports
    assert not imported_core_modules
    assert direct_calls.isdisjoint(legacy_wrappers)
    assert not module_qualified_calls


def test_seeded_stale_section_must_be_replaced(oracle, roots) -> None:
    test_scenario = scenario("unit", section("project", "random-notes.txt", preserve_user_content=True))

    oracle.seed_user_owned_content(test_scenario)
    seeded = roots["project"] / "random-notes.txt"
    assert file_effects.USER_SENTINEL in seeded.read_text(encoding="utf-8")
    assert file_effects.STALE_GRAPHIFY_SENTINEL in seeded.read_text(encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is False

    seeded.write_text(f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n", encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is True


def test_text_policy_is_declared_not_inferred_from_known_file_names(oracle, roots) -> None:
    known_without_policy = ExpectedPath("project", "AGENTS.md", marker=platform_specs.GRAPHIFY_MARKER)
    declared_random_path = section("project", "not-a-platform-file.txt", preserve_user_content=True)
    test_scenario = scenario("unit", known_without_policy, declared_random_path)

    oracle.seed_user_owned_content(test_scenario)

    assert not (roots["project"] / "AGENTS.md").exists()
    assert (roots["project"] / "not-a-platform-file.txt").exists()

    (roots["project"] / "AGENTS.md").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    (roots["project"] / "not-a-platform-file.txt").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )

    known_check, declared_check = oracle.assert_expected_files(test_scenario)
    assert known_check["ok"] is True
    assert "stale_replaced" not in str(known_check["detail"])
    assert declared_check["ok"] is False
    assert "stale_replaced=False" in str(declared_check["detail"])


def test_legacy_expected_path_with_text_policy_dispatches_as_text_section(oracle, roots) -> None:
    legacy_text_policy = ExpectedPath(
        "project",
        "notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True, require_user_content_on_uninstall=True),
    )
    test_scenario = scenario("unit", legacy_text_policy)

    oracle.seed_user_owned_content(test_scenario)

    assert (roots["project"] / "notes.txt").read_text(encoding="utf-8") == f"# User Notes\n\n{file_effects.USER_SENTINEL}\n"


def test_seed_user_owned_content_writes_only_declared_preserved_text_surfaces(oracle, roots) -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    legacy_text_policy = ExpectedPath(
        "project",
        "legacy-notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True),
    )
    no_preserve_text_section = section("project", "no-preserve.md")
    plain_surface = ExpectedPath("project", "plain.txt")
    json_surface = ExpectedPath("project", "settings.json", content_kind="json", marker="graphify")
    skill_surface = expected_skill("project", ".unit/graphify/SKILL.md")
    test_scenario = scenario(
        "unit",
        stale_section,
        legacy_text_policy,
        no_preserve_text_section,
        plain_surface,
        json_surface,
        skill_surface,
    )

    oracle.seed_user_owned_content(test_scenario)

    assert (roots["project"] / "stale-notes.md").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n"
        f"{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n\n"
        "## User Section\nThis section should survive Graphify install and uninstall.\n"
    )
    assert (roots["project"] / "legacy-notes.txt").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effects.USER_SENTINEL}\n"
    )
    assert not (roots["project"] / "no-preserve.md").exists()
    assert not (roots["project"] / "plain.txt").exists()
    assert not (roots["project"] / "settings.json").exists()
    assert not (roots["project"] / ".unit/graphify/SKILL.md").exists()


def test_uninstall_requires_seeded_user_content_to_survive(oracle, roots) -> None:
    test_scenario = scenario("unit", section("project", "random-notes.txt", preserve_user_content=True))
    oracle.seed_user_owned_content(test_scenario)
    (roots["project"] / "random-notes.txt").unlink()

    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert check["detail"] == "user_content_file_missing"

    (roots["project"] / "random-notes.txt").write_text("# User Notes\n", encoding="utf-8")
    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert "user_content_preserved=False" in str(check["detail"])


def test_unexpected_graphify_files_render_success_and_failure_records(oracle, roots) -> None:
    expected = roots["project"] / "AGENTS.md"
    expected.write_text("## graphify\n", encoding="utf-8")
    excluded = roots["home"] / ".local/lib/python3.12/site-packages/graphify_noise.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("graphify dependency noise\n", encoding="utf-8")
    unexpected_path = roots["project"] / "notes/graphify.md"
    unexpected_path.parent.mkdir(parents=True)
    unexpected_path.write_text("generated by graphify\n", encoding="utf-8")
    marker_only = roots["user_cwd"] / "notes.md"
    marker_only.write_text("Generated by Graphify\n", encoding="utf-8")
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    checks = oracle.assert_no_unexpected_graphify_files(
        test_scenario,
        phase="install",
        expected_keys={("project", "AGENTS.md"), ("user_cwd", "notes.md")},
    )

    assert checks == [
        {
            "path": str(unexpected_path),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_install",
            "root": "project",
            "relative": "notes/graphify.md",
        }
    ]

    unexpected_path.unlink()
    success = oracle.assert_no_unexpected_graphify_files(
        test_scenario,
        phase="repeat_install",
        expected_keys={("project", "AGENTS.md"), ("user_cwd", "notes.md")},
    )

    assert success == [{"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"}]


def test_copy_generated_files_filters_relevance_and_preserves_root_relative_layout(oracle, roots, tmp_path) -> None:
    skill = roots["home"] / ".codex/skills/graphify/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# graphify skill\n", encoding="utf-8")
    (skill.parent / ".graphify_version").write_text("1.2.3", encoding="utf-8")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    dependency = roots["home"] / ".local/lib/python3.12/site-packages/example.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("graphify dependency noise\n", encoding="utf-8")
    shared = roots["project"] / "AGENTS.md"
    shared.write_text("## graphify\n", encoding="utf-8")
    nested = roots["project"] / "nested/graphify-output.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("generated by graphify\n", encoding="utf-8")
    unrelated = roots["project"] / "notes.md"
    unrelated.write_text("user notes\n", encoding="utf-8")
    excluded_project = roots["project"] / ".cache/graphify/cache.txt"
    excluded_project.parent.mkdir(parents=True)
    excluded_project.write_text("graphify cache\n", encoding="utf-8")
    test_scenario = Scenario(
        platform="claude",
        scope="user",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="user_cwd",
        expected=(expected_skill("home", ".codex/skills/graphify/SKILL.md"),),
    )

    artifact_dir = tmp_path / "artifact"
    stale_archive = artifact_dir / "generated-files/project/stale.txt"
    stale_archive.parent.mkdir(parents=True)
    stale_archive.write_text("old archive\n", encoding="utf-8")

    oracle.copy_generated_files(test_scenario, artifact_dir)

    generated = artifact_dir / "generated-files"
    assert not stale_archive.exists()
    assert (generated / "home/.codex/skills/graphify/SKILL.md").exists()
    assert (generated / "home/.codex/skills/graphify/.graphify_version").exists()
    assert (generated / "home/.codex/skills/graphify/references/query.md").exists()
    assert (generated / "project/AGENTS.md").exists()
    assert (generated / "project/nested/graphify-output.txt").exists()
    assert not (generated / "home/.local/lib/python3.12/site-packages/example.py").exists()
    assert not (generated / "project/.cache/graphify/cache.txt").exists()
    assert not (generated / "project/notes.md").exists()


def test_copy_generated_files_keeps_walking_decisions_and_copying_in_oracle(oracle, roots, tmp_path, monkeypatch) -> None:
    included = roots["project"] / "nested/keep.txt"
    included.parent.mkdir(parents=True)
    included.write_text("generated by graphify\n", encoding="utf-8")
    skipped = roots["project"] / "nested/skip.txt"
    skipped.write_text("generated by graphify but ignored by decision\n", encoding="utf-8")
    copied: list[tuple[Path, Path]] = []

    def copy2(source, destination) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        copied.append((source_path, destination_path))
        destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(file_effects.shutil, "copy2", copy2)

    class RecordingCopyOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "walked_roots", [])
            object.__setattr__(self, "decisions", [])

        def pruned_file_walk(self, base: Path):
            self.walked_roots.append(base)
            if base == roots["project"]:
                yield included
                yield skipped

        def generated_file_decision(
            self,
            scenario_arg,
            root_name,
            relative,
            path,
            *,
            apply_excludes,
            expected_keys=None,
        ):
            self.decisions.append(
                {
                    "scenario": scenario_arg.platform,
                    "root": root_name,
                    "relative": relative.as_posix(),
                    "path": path,
                    "apply_excludes": apply_excludes,
                    "expected_keys": expected_keys,
                }
            )
            observation = install_surface_core.GeneratedFileObservation(
                root_name=root_name,
                relative=relative,
                suffix=path.suffix,
                file_size=path.stat().st_size,
                mentions_expected_marker=False,
                expected_key=False,
                skill_sidecar_relative=False,
                excluded_path=False,
                relative_substring_match=False,
                small_text_candidate=False,
            )
            return install_surface_core.GeneratedFileDecision(
                observation,
                is_relevant=relative == Path("nested/keep.txt"),
                is_ignored=False,
            )

    recording_oracle = RecordingCopyOracle(oracle)
    archive_scenario = scenario("unit", ExpectedPath("project", "declared.txt"))
    artifact_dir = tmp_path / "artifact"

    recording_oracle.copy_generated_files(archive_scenario, artifact_dir)

    assert recording_oracle.walked_roots == [roots["home"], roots["project"], roots["user_cwd"]]
    assert recording_oracle.decisions == [
        {
            "scenario": "unit",
            "root": "project",
            "relative": "nested/keep.txt",
            "path": included,
            "apply_excludes": True,
            "expected_keys": {("project", "declared.txt")},
        },
        {
            "scenario": "unit",
            "root": "project",
            "relative": "nested/skip.txt",
            "path": skipped,
            "apply_excludes": True,
            "expected_keys": {("project", "declared.txt")},
        },
    ]
    assert copied == [
        (
            included,
            artifact_dir / "generated-files/project/nested/keep.txt",
        )
    ]
    assert (artifact_dir / "generated-files/project/nested/keep.txt").read_text(encoding="utf-8") == "generated by graphify\n"
    assert not (artifact_dir / "generated-files/project/nested/skip.txt").exists()


def test_scenario_file_effects_adapter_preserves_repeat_install_and_universal_uninstall_shapes(oracle, roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = file_effects.ScenarioFileEffectsAdapter(oracle, write_manifest, equivalence_check)
    repeat_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    before = {
        "project/AGENTS.md": {"exists": True, "sha256": "a"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/AGENTS.md": {"exists": True, "sha256": "b"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }

    repeat_checks = adapter.repeat_install_checks(repeat_scenario, before, after, phase="repeat_install")

    assert repeat_checks == [
        {"path": "project/AGENTS.md", "ok": False, "detail": "changed_after_repeat_install"},
        {"path": "project/notes.md", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"},
    ]

    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", ".second/graphify/SKILL.md"))
    (roots["project"] / "first.md").write_text("still installed\n", encoding="utf-8")
    expected_generated = roots["home"] / ".second/graphify/SKILL.md"
    expected_generated.parent.mkdir(parents=True)
    expected_generated.write_text("expected generated path may remain\n", encoding="utf-8")
    unexpected_generated = roots["project"] / "leftover/graphify.md"
    unexpected_generated.parent.mkdir(parents=True)
    unexpected_generated.write_text("generated by graphify\n", encoding="utf-8")
    install_checks = [{"path": "install", "ok": True, "detail": "installed"}]

    universal_checks = adapter.universal_uninstall_checks(repeat_scenario, (first, second), install_checks)

    assert universal_checks == [
        {"path": "install", "ok": True, "detail": "installed"},
        {
            "path": str(roots["project"] / "first.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "project",
            "relative": "first.md",
        },
        {
            "path": str(roots["home"] / ".second/graphify/SKILL.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "home",
            "relative": ".second/graphify/SKILL.md",
        },
        {
            "path": str(unexpected_generated),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_universal_uninstall",
            "root": "project",
            "relative": "leftover/graphify.md",
        },
    ]


def test_scenario_file_effects_adapter_orders_universal_uninstall_check_groups(oracle) -> None:
    calls: list[tuple[object, ...]] = []

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )

        def assert_uninstalled(self, scenario_arg):
            calls.append(("assert_uninstalled", scenario_arg.platform))
            if scenario_arg.platform == "first":
                return [
                    {"path": "first.md", "ok": True, "detail": "removed"},
                    {"path": "first-sidecar", "ok": True, "detail": "removed"},
                ]
            return [{"path": "second.md", "ok": True, "detail": "removed"}]

        def assert_no_unexpected_graphify_files(self, scenario_arg, *, phase, expected_keys=None):
            calls.append(("assert_no_unexpected_graphify_files", scenario_arg.platform, phase, expected_keys))
            return [
                {"path": "leftover.md", "ok": False, "detail": "unexpected_graphify_related_file_after_universal_uninstall"},
                {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_universal_uninstall"},
            ]

    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = file_effects.ScenarioFileEffectsAdapter(RecordingOracle(oracle), write_manifest, equivalence_check)
    runner = scenario("runner", ExpectedPath("project", "runner.md"))
    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", "second.md"))
    install_checks = [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
    ]

    assert adapter.universal_uninstall_checks(runner, (first, second), install_checks) == [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
        {"path": "first.md", "ok": True, "detail": "removed"},
        {"path": "first-sidecar", "ok": True, "detail": "removed"},
        {"path": "second.md", "ok": True, "detail": "removed"},
        {"path": "leftover.md", "ok": False, "detail": "unexpected_graphify_related_file_after_universal_uninstall"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_universal_uninstall"},
    ]
    assert calls == [
        ("assert_uninstalled", "first"),
        ("assert_uninstalled", "second"),
        (
            "assert_no_unexpected_graphify_files",
            "runner",
            "universal_uninstall",
            {("project", "first.md"), ("home", "second.md")},
        ),
    ]


def test_scenario_file_effects_adapter_pins_delegation_boundaries(oracle, roots, tmp_path) -> None:
    calls: list[tuple[object, ...]] = []

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )

        def seed_user_owned_content(self, scenario_arg):
            calls.append(("seed_user_owned_content", scenario_arg.platform))

        def scenario_file_state(self, scenario_arg):
            calls.append(("scenario_file_state", scenario_arg.platform))
            return {"state": {"exists": True}}

        def assert_expected_files(self, scenario_arg):
            calls.append(("assert_expected_files", scenario_arg.platform))
            return [{"path": "expected", "ok": True, "detail": "expected"}]

        def assert_scope_boundaries(self, scenario_arg):
            calls.append(("assert_scope_boundaries", scenario_arg.platform))
            return [{"path": "scope", "ok": True, "detail": "scope"}]

        def assert_no_unexpected_graphify_files(self, scenario_arg, *, phase, expected_keys=None):
            calls.append(("assert_no_unexpected_graphify_files", scenario_arg.platform, phase, expected_keys))
            return [{"path": "unexpected", "ok": True, "detail": f"none_after_{phase}"}]

        def copy_generated_files(self, scenario_arg, artifact_dir):
            calls.append(("copy_generated_files", scenario_arg.platform, artifact_dir))

        def seed_stale_skill_sidecars(self, scenario_arg):
            calls.append(("seed_stale_skill_sidecars", scenario_arg.platform))
            return [{"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}]

        def assert_installed_skill_sidecars(self, scenario_arg):
            calls.append(("assert_installed_skill_sidecars", scenario_arg.platform))
            return [{"path": "sidecars", "ok": True, "detail": "sidecars"}]

        def assert_uninstalled(self, scenario_arg):
            calls.append(("assert_uninstalled", scenario_arg.platform))
            return [{"path": f"uninstalled-{scenario_arg.platform}", "ok": True, "detail": "removed"}]

    def write_manifest(path, roots_arg, **kwargs) -> None:
        calls.append(("write_manifest", path, roots_arg, kwargs))

    def equivalence_check(scenario_arg, env, artifact_dir):
        calls.append(("equivalence_check", scenario_arg.platform, env, artifact_dir))
        return [{"path": "equivalence", "ok": True, "detail": "equivalent"}]

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    adapter_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    artifact_dir = tmp_path / "artifact"
    manifest_path = tmp_path / "manifest.json"

    assert adapter.seed_scenario_inputs(adapter_scenario) is None
    adapter.write_manifest(manifest_path, roots, scenario=adapter_scenario)
    assert adapter.capture_state(adapter_scenario) == {"state": {"exists": True}}
    assert adapter.install_checks(adapter_scenario) == [
        {"path": "expected", "ok": True, "detail": "expected"},
        {"path": "scope", "ok": True, "detail": "scope"},
    ]
    assert adapter.unexpected_checks(adapter_scenario, phase="install") == [
        {"path": "unexpected", "ok": True, "detail": "none_after_install"}
    ]
    assert adapter.archive_generated_files(adapter_scenario, artifact_dir) is None
    assert adapter.repeat_install_checks(
        adapter_scenario,
        {"project/AGENTS.md": {"exists": True, "sha256": "a"}},
        {"project/AGENTS.md": {"exists": True, "sha256": "a"}},
        phase="repeat_install",
    ) == [
        {"path": "project/AGENTS.md", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected", "ok": True, "detail": "none_after_repeat_install"},
    ]
    assert adapter.seed_stale_sidecar_repair(adapter_scenario) == [
        {"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    assert adapter.stale_sidecar_repair_checks(adapter_scenario, phase="stale_sidecar_repair") == [
        {"path": "sidecars", "ok": True, "detail": "sidecars"},
        {"path": "unexpected", "ok": True, "detail": "none_after_stale_sidecar_repair"},
    ]
    assert adapter.uninstall_checks(adapter_scenario, phase="uninstall") == [
        {"path": "uninstalled-unit", "ok": True, "detail": "removed"},
        {"path": "unexpected", "ok": True, "detail": "none_after_uninstall"},
    ]
    assert adapter.equivalence_checks(adapter_scenario, {"HOME": str(roots["home"])}, artifact_dir) == [
        {"path": "equivalence", "ok": True, "detail": "equivalent"}
    ]
    assert adapter.universal_uninstall_checks(
        adapter_scenario,
        (scenario("first", ExpectedPath("project", "first.md")), scenario("second", ExpectedPath("home", "second.md"))),
        [{"path": "install", "ok": True, "detail": "installed"}],
    ) == [
        {"path": "install", "ok": True, "detail": "installed"},
        {"path": "uninstalled-first", "ok": True, "detail": "removed"},
        {"path": "uninstalled-second", "ok": True, "detail": "removed"},
        {"path": "unexpected", "ok": True, "detail": "none_after_universal_uninstall"},
    ]
    assert adapter.disposable_artifact_checks(roots["project"] / "graphify-out", removed=True) == [
        {"path": str(roots["project"] / "graphify-out"), "ok": True, "detail": "removed"}
    ]

    assert calls == [
        ("seed_user_owned_content", "unit"),
        ("write_manifest", manifest_path, roots, {"scenario": adapter_scenario}),
        ("scenario_file_state", "unit"),
        ("assert_expected_files", "unit"),
        ("assert_scope_boundaries", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "install", None),
        ("copy_generated_files", "unit", artifact_dir),
        ("assert_no_unexpected_graphify_files", "unit", "repeat_install", None),
        ("seed_stale_skill_sidecars", "unit"),
        ("assert_installed_skill_sidecars", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "stale_sidecar_repair", None),
        ("assert_uninstalled", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "uninstall", None),
        ("equivalence_check", "unit", {"HOME": str(roots["home"])}, artifact_dir),
        ("assert_uninstalled", "first"),
        ("assert_uninstalled", "second"),
        (
            "assert_no_unexpected_graphify_files",
            "unit",
            "universal_uninstall",
            {("project", "first.md"), ("home", "second.md")},
        ),
    ]


def test_scenario_file_effects_adapter_preserves_setup_method_shapes(oracle) -> None:
    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "calls", [])

        def seed_user_owned_content(self, scenario_arg):
            self.calls.append(("seed_user_owned_content", scenario_arg.platform))

        def seed_stale_skill_sidecars(self, scenario_arg):
            self.calls.append(("seed_stale_skill_sidecars", scenario_arg.platform))
            return [{"ok": True, "detail": "seeded_stale_reference_fragment"}]

    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    setup_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    assert adapter.seed_scenario_inputs(setup_scenario) is None
    assert adapter.seed_stale_sidecar_repair(setup_scenario) == [
        {"ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    assert recording_oracle.calls == [
        ("seed_user_owned_content", "unit"),
        ("seed_stale_skill_sidecars", "unit"),
    ]


def test_universal_uninstall_derives_expected_keys_through_installer_core(oracle) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "unexpected_calls", [])

        def assert_uninstalled(self, scenario_arg):
            return []

        def assert_no_unexpected_graphify_files(self, scenario_arg, *, phase, expected_keys=None):
            self.unexpected_calls.append((scenario_arg.platform, phase, expected_keys))
            return []

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    runner = scenario("unit", ExpectedPath("project", "runner.md"))
    installed = (
        scenario("first", ExpectedPath("project", "first.md")),
        scenario("second", ExpectedPath("home", ".second/graphify/SKILL.md")),
    )

    adapter.universal_uninstall_checks(runner, installed, [])

    assert recording_oracle.unexpected_calls == [
        (
            "unit",
            "universal_uninstall",
            {("project", "first.md"), ("home", ".second/graphify/SKILL.md")},
        )
    ]
