from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.effects import file_effect_generated_artifacts
from tools.install_sandbox.effects import file_effect_oracle
from tools.install_sandbox.effects import file_effect_state
from tools.install_sandbox import install_surface_core
from tools.install_sandbox import install_surface_generated
from tools.install_sandbox import platform_specs
from tools.install_sandbox.effects import scenario_file_effects_adapter
from tools.install_sandbox.platform_specs import ExpectedPath, InstallSurface, Scenario
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution

from install_target_test_support import scenario_for

# Sandbox generated/seeded artifact records live here. Direct generated-file
# Installer Core decisions remain in test_install_surface_core_generated.py and
# state-plan decisions remain in test_install_surface_core_state_plans.py.


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


def test_seeded_stale_section_must_be_replaced(oracle, roots) -> None:
    test_scenario = scenario("unit", section("project", "random-notes.txt", preserve_user_content=True))

    oracle.seed_user_owned_content(test_scenario)
    seeded = roots["project"] / "random-notes.txt"
    assert file_effect_state.USER_SENTINEL in seeded.read_text(encoding="utf-8")
    assert file_effect_state.STALE_GRAPHIFY_SENTINEL in seeded.read_text(encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is False

    seeded.write_text(f"# User Notes\n\n{file_effect_state.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n", encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is True


def test_text_policy_is_declared_not_inferred_from_known_file_names(oracle, roots) -> None:
    known_without_policy = ExpectedPath("project", "AGENTS.md", marker=platform_specs.GRAPHIFY_MARKER)
    declared_random_path = section("project", "not-a-platform-file.txt", preserve_user_content=True)
    test_scenario = scenario("unit", known_without_policy, declared_random_path)

    oracle.seed_user_owned_content(test_scenario)

    assert not (roots["project"] / "AGENTS.md").exists()
    assert (roots["project"] / "not-a-platform-file.txt").exists()

    (roots["project"] / "AGENTS.md").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    (roots["project"] / "not-a-platform-file.txt").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n",
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

    assert (roots["project"] / "notes.txt").read_text(encoding="utf-8") == f"# User Notes\n\n{file_effect_state.USER_SENTINEL}\n"


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
        f"# User Notes\n\n{file_effect_state.USER_SENTINEL}\n\n"
        f"{platform_specs.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n\n"
        "## User Section\nThis section should survive Graphify install and uninstall.\n"
    )
    assert (roots["project"] / "legacy-notes.txt").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effect_state.USER_SENTINEL}\n"
    )
    assert not (roots["project"] / "no-preserve.md").exists()
    assert not (roots["project"] / "plain.txt").exists()
    assert not (roots["project"] / "settings.json").exists()
    assert not (roots["project"] / ".unit/graphify/SKILL.md").exists()


def test_file_effect_state_seeds_user_owned_content(roots) -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    test_scenario = scenario("unit", stale_section)

    file_effect_state.seed_user_owned_content(test_scenario, roots.__getitem__)

    assert (roots["project"] / "stale-notes.md").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effect_state.USER_SENTINEL}\n\n"
        f"{platform_specs.GRAPHIFY_MARKER}\n{file_effect_state.STALE_GRAPHIFY_SENTINEL}\n\n"
        "## User Section\nThis section should survive Graphify install and uninstall.\n"
    )


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


def test_generated_artifact_module_renders_unexpected_graphify_file_records(oracle, roots) -> None:
    unexpected_path = roots["project"] / "notes/graphify.md"
    unexpected_path.parent.mkdir(parents=True)
    unexpected_path.write_text("generated by graphify\n", encoding="utf-8")
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    checks = file_effect_generated_artifacts.assert_no_unexpected_graphify_files(
        test_scenario,
        roots,
        oracle.packaged_reference_resolution,
        phase="install",
        pruned_file_walk_for=oracle.pruned_file_walk,
        generated_file_decision_for=oracle.generated_file_decision,
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


def test_agents_skill_sidecars_are_relevant_generated_file_effects() -> None:
    test_scenario = scenario_for("agents", "user")

    assert install_surface_generated.is_skill_sidecar_relative(
        test_scenario.expected,
        "home",
        Path(".agents/skills/graphify/.graphify_version"),
    )
    assert install_surface_generated.is_skill_sidecar_relative(
        test_scenario.expected,
        "home",
        Path(".agents/skills/graphify/references/query.md"),
    )
    assert install_surface_generated.is_skill_sidecar_relative(
        test_scenario.expected,
        "home",
        Path(".agents/skills/graphify/references.tmp/partial.md"),
    )
    assert not install_surface_generated.is_skill_sidecar_relative(
        test_scenario.expected,
        "project",
        Path(".agents/skills/graphify/.graphify_version"),
    )


def test_copy_generated_files_archives_agents_skill_sidecars(oracle, roots, tmp_path) -> None:
    test_scenario = scenario_for("agents", "project")
    skill = roots["project"] / ".agents/skills/graphify/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# graphify skill\n", encoding="utf-8")
    (skill.parent / ".graphify_version").write_text("9.9.9", encoding="utf-8")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")

    oracle.copy_generated_files(test_scenario, tmp_path)

    generated = tmp_path / "generated-files/project/.agents/skills/graphify"
    assert (generated / "SKILL.md").exists()
    assert (generated / ".graphify_version").exists()
    assert (generated / "references/query.md").exists()


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

    monkeypatch.setattr(file_effect_generated_artifacts.shutil, "copy2", copy2)

    class RecordingCopyOracle(file_effect_oracle.FileEffectOracle):
        def __init__(self, wrapped: file_effect_oracle.FileEffectOracle) -> None:
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
            observation = install_surface_generated.GeneratedFileObservation(
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
            return install_surface_generated.GeneratedFileDecision(
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


def test_universal_uninstall_derives_expected_keys_through_installer_core(oracle) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    class RecordingOracle(file_effect_oracle.FileEffectOracle):
        def __init__(self, wrapped: file_effect_oracle.FileEffectOracle) -> None:
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
    adapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
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
