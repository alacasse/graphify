from __future__ import annotations

from pathlib import Path

from tools.install_sandbox import install_surface_core
from tools.install_sandbox import platform_specs
from tools.install_sandbox.platform_specs import ExpectedPath, InstallSurface
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


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


def test_install_surface_core_derives_ordered_idempotency_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_core.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
        installed_skill_reference_relatives={
            ("home", ".codex/skills/graphify/SKILL.md"): {
                Path(".codex/skills/graphify/references/local.md"),
            },
        },
    )

    assert [entry.key for entry in plan] == [
        "project/notes.md",
        "home/.codex/skills/graphify/SKILL.md",
        "home/.codex/skills/graphify/.graphify_version",
        "home/.codex/skills/graphify/references",
        "home/.codex/skills/graphify/references.tmp",
        "home/.codex/skills/graphify/references/local.md",
        "home/.codex/skills/graphify/references/query.md",
    ]
    assert plan[0].root_name == "project"
    assert plan[0].relative == Path("notes.md")
    assert plan[0].marker == platform_specs.GRAPHIFY_MARKER
    assert plan[0].text_expectation is not None
    assert plan[0].text_expectation.preserve_user_content is True
    assert plan[1].root_name == "home"
    assert plan[1].relative == Path(".codex/skills/graphify/SKILL.md")
    assert plan[2].marker is None
    assert plan[2].text_expectation is None


def test_install_surface_core_derives_ordered_idempotency_state_changes() -> None:
    before = {
        "project/changed.md": {"exists": True, "sha256": "before"},
        "project/removed.md": {"exists": True, "sha256": "removed"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/added.md": {"exists": True, "sha256": "added"},
        "project/changed.md": {"exists": True, "sha256": "after"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }

    changes = install_surface_core.idempotency_state_changes(before, after)

    assert changes == (
        install_surface_core.IdempotencyStateChange("project/added.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/changed.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/removed.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/stable.md", stable=True),
    )


def test_install_surface_core_derives_user_content_seed_plans() -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    legacy_text_policy = ExpectedPath(
        "home",
        "legacy-notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True),
    )
    no_preserve_text_section = section("project", "no-preserve.md")
    plain_surface = ExpectedPath("project", "plain.txt")
    json_surface = ExpectedPath("project", "settings.json", content_kind="json", marker="graphify")

    plans = install_surface_core.user_content_seed_plans(
        (
            stale_section,
            legacy_text_policy,
            no_preserve_text_section,
            plain_surface,
            json_surface,
        )
    )

    assert plans == (
        install_surface_core.UserContentSeedPlan(
            root_name="project",
            relative=Path("stale-notes.md"),
            text=(
                f"# User Notes\n\n{install_surface_core.USER_SENTINEL}\n\n"
                f"{platform_specs.GRAPHIFY_MARKER}\n{install_surface_core.STALE_GRAPHIFY_SENTINEL}\n\n"
                "## User Section\nThis section should survive Graphify install and uninstall.\n"
            ),
        ),
        install_surface_core.UserContentSeedPlan(
            root_name="home",
            relative=Path("legacy-notes.txt"),
            text=f"# User Notes\n\n{install_surface_core.USER_SENTINEL}\n",
        ),
    )


def test_install_surface_core_derives_stale_sidecar_seed_plans() -> None:
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    plain_surface = ExpectedPath("project", "AGENTS.md")

    plans = install_surface_core.stale_sidecar_seed_plans(
        (plain_surface, skill),
        resolution("available", ("query.md",)),
    )

    assert plans == (
        install_surface_core.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references/stale-sandbox-fragment.md"),
            text="stale sandbox reference fragment\n",
            kind="stale_reference_fragment",
        ),
        install_surface_core.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references.tmp/partial.md"),
            text="partial staged reference fragment\n",
            kind="staged_reference_fragment",
        ),
    )
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("empty")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("missing")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("not_directory")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("intentionally_absent")) == ()
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("no_eligible_bundle")) == ()
    assert install_surface_core.stale_sidecar_seed_plans((plain_surface,), resolution("available", ("query.md",))) == ()


def test_expected_generated_keys_reuse_generated_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_core.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
    )

    assert install_surface_core.expected_generated_relative_keys((notes, skill), resolution("available", ("query.md",))) == {
        (entry.root_name, entry.relative.as_posix()) for entry in plan
    }


def json_status_from_loaded_data(surface: InstallSurface, data: object) -> install_surface_core.InstallSurfaceStatus:
    return install_surface_core.installed_surface_status_from_observation(
        surface,
        install_surface_core.InstallSurfaceObservation(
            path=Path(f"/observed/{surface.relative}"),
            exists=True,
            is_file=True,
            json_data=data,
            json_loaded=True,
        ),
    )


def registered_json_status(platform: str, scope: str, relative: str, data: object) -> install_surface_core.InstallSurfaceStatus:
    test_scenario = platform_specs.DEFAULT_SCENARIO_REGISTRY.make_scenario(platform, scope)
    assert test_scenario is not None
    entry = next(item for item in test_scenario.expected if item.relative == relative)
    return json_status_from_loaded_data(entry, data)


def test_install_surface_core_classifies_generated_file_relevance_decisions() -> None:
    skill_entry = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    ordinary_entry = InstallSurface("project", "AGENTS.md")
    expected = (skill_entry, ordinary_entry)
    expectation = platform_specs.GeneratedFileExpectation(
        relative_substrings=("graphify",),
        text_suffixes=(".md",),
        content_markers=("Graphify",),
        include_user_content_sentinel=True,
        max_text_bytes=12,
    )

    assert install_surface_core.expected_generated_relative_keys(expected, resolution("available", ("query.md",))) == {
        ("home", ".codex/skills/graphify/SKILL.md"),
        ("home", ".codex/skills/graphify/.graphify_version"),
        ("home", ".codex/skills/graphify/references.tmp"),
        ("home", ".codex/skills/graphify/references"),
        ("home", ".codex/skills/graphify/references/query.md"),
        ("project", "AGENTS.md"),
    }
    assert install_surface_core.is_excluded_generated_path(Path(".local/lib/example.py"), (".local", ".cache", "__pycache__", ".pytest_cache")) is True
    assert install_surface_core.is_expected_generated_key(expected, "project", Path("AGENTS.md")) is True
    assert install_surface_core.is_skill_sidecar_relative(expected, "home", Path(".codex/skills/graphify/references/nested/query.md")) is True
    assert install_surface_core.is_small_text_candidate(expectation, file_size=12, suffix=".md") is True
    assert install_surface_core.is_small_text_candidate(expectation, file_size=13, suffix=".md") is False
    assert install_surface_core.is_small_text_candidate(expectation, file_size=12, suffix=".bin") is False
    assert install_surface_core.text_mentions_expected_generated_marker(expectation, "generated by graphify") is True
    assert install_surface_core.text_mentions_expected_generated_marker(expectation, install_surface_core.USER_SENTINEL) is True

    candidate = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path("notes.md"),
        file_size=12,
        mentions_expected_marker=False,
        excluded_path=False,
    )
    assert candidate.root_name == "project"
    assert candidate.relative == Path("notes.md")
    assert candidate.suffix == ".md"
    assert candidate.file_size == 12
    assert candidate.expected_key is False
    assert candidate.skill_sidecar_relative is False
    assert candidate.excluded_path is False
    assert candidate.relative_substring_match is False
    assert candidate.small_text_candidate is True
    assert candidate.needs_text_marker_match is True
    assert install_surface_core.decide_generated_file_observation(candidate).should_include is False

    marker_match = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path("notes.md"),
        file_size=12,
        mentions_expected_marker=True,
        excluded_path=False,
    )
    marker_decision = install_surface_core.decide_generated_file_observation(marker_match)
    assert marker_decision.is_relevant is True
    assert marker_decision.is_ignored is False
    assert marker_decision.should_include is True

    excluded = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path(".cache/graphify.txt"),
        file_size=12,
        mentions_expected_marker=True,
        excluded_path=True,
    )
    excluded_decision = install_surface_core.decide_generated_file_observation(excluded)
    assert excluded.path_relevant is True
    assert excluded.needs_text_marker_match is False
    assert excluded_decision.is_relevant is True
    assert excluded_decision.is_ignored is True
    assert excluded_decision.should_include is False

    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("AGENTS.md"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "home",
            Path(".codex/skills/graphify/.graphify_version"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes/graphify-log.bin"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=True,
            mentions_expected_marker=True,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=True,
            mentions_expected_marker=False,
        )
        is False
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=False,
            mentions_expected_marker=True,
        )
        is False
    )


def test_install_surface_core_derives_generated_artifact_copy_destination() -> None:
    plan = install_surface_core.generated_artifact_copy_plan(
        "project",
        Path("nested/graphify-output.txt"),
    )

    assert plan == install_surface_core.GeneratedArtifactCopyPlan(
        root_name="project",
        source_relative=Path("nested/graphify-output.txt"),
        destination_relative=Path("project/nested/graphify-output.txt"),
    )


def test_install_surface_core_decides_file_fingerprint_from_observed_facts() -> None:
    notes_text = f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n## graphify\n{install_surface_core.STALE_GRAPHIFY_SENTINEL}\n"

    assert install_surface_core.file_fingerprint_from_observation(
        install_surface_core.FileFingerprintObservation(exists=False)
    ) == {"exists": False}
    assert install_surface_core.file_fingerprint_from_observation(
        install_surface_core.FileFingerprintObservation(exists=True, kind="dir")
    ) == {"exists": True, "kind": "dir"}

    fingerprint = install_surface_core.file_fingerprint_from_observation(
        install_surface_core.FileFingerprintObservation(
            exists=True,
            kind="file",
            data=notes_text.encode("utf-8"),
            text=notes_text,
        ),
        "## graphify",
        platform_specs.TextExpectation(preserve_user_content=True, repair_stale_graphify_section=True),
    )

    assert fingerprint["exists"] is True
    assert fingerprint["kind"] == "file"
    assert fingerprint["size"] == len(notes_text.encode("utf-8"))
    assert fingerprint["marker_count"] == 1
    assert fingerprint["user_content_preserved"] is True
    assert fingerprint["stale_graphify_present"] is True
    assert isinstance(fingerprint["sha256"], str)


def test_install_surface_core_decides_installed_status_from_observed_facts() -> None:
    missing = InstallSurface("project", "missing.txt")
    missing_observation = install_surface_core.InstallSurfaceObservation(
        path=Path("/observed/missing.txt"),
        exists=False,
    )

    missing_status = install_surface_core.installed_surface_status_from_observation(missing, missing_observation)

    assert missing_status == install_surface_core.InstallSurfaceStatus(
        Path("/observed/missing.txt"),
        ok=False,
        detail="missing",
    )

    wrong_kind = InstallSurface("project", "wrong-kind", kind="dir")
    wrong_kind_status = install_surface_core.installed_surface_status_from_observation(
        wrong_kind,
        install_surface_core.InstallSurfaceObservation(
            path=Path("/observed/wrong-kind"),
            exists=True,
            is_file=True,
            is_dir=False,
        ),
    )

    assert wrong_kind_status.ok is False
    assert wrong_kind_status.detail == "expected_directory_but_not_directory"

    text_surface = section("project", "notes.md", preserve_user_content=True)
    text_status = install_surface_core.installed_surface_status_from_observation(
        text_surface,
        install_surface_core.InstallSurfaceObservation(
            path=Path("/observed/notes.md"),
            exists=True,
            is_file=True,
            text=f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n",
        ),
    )

    assert text_status.ok is True
    assert text_status.detail == "marker_count=1; user_content_preserved; stale_replaced=True"

    json_surface = InstallSurface("project", "settings.json", content_kind="json", marker="graphify")
    json_status = json_status_from_loaded_data(json_surface, {"hooks": [{"command": "graphify query"}]})

    assert json_status.ok is True
    assert json_status.detail == "valid_json=true; schema=generic_marker; marker_present=True"

    invalid_json_status = install_surface_core.installed_surface_status_from_observation(
        json_surface,
        install_surface_core.InstallSurfaceObservation(
            path=Path("/observed/settings.json"),
            exists=True,
            is_file=True,
            json_error_detail="invalid_json=Expecting value",
        ),
    )

    assert invalid_json_status.ok is False
    assert invalid_json_status.detail == "invalid_json=Expecting value"


def test_install_surface_core_decides_kind_status_from_observed_facts() -> None:
    surface = InstallSurface("project", "installed.txt")
    observed_path = Path("/observed/installed.txt")

    status = install_surface_core.install_surface_kind_status_from_observation(
        surface,
        install_surface_core.InstallSurfaceObservation(
            path=observed_path,
            exists=True,
            is_file=True,
            is_dir=False,
        ),
    )

    assert status.path == observed_path
    assert status.ok is True
    assert status.detail == "file"


def test_installed_surface_status_observation_helper_preserves_paths_and_details() -> None:
    missing = InstallSurface("project", "missing.txt")
    missing_path = Path("/observed/missing.txt")

    assert install_surface_core.installed_surface_status_from_observation(
        missing,
        install_surface_core.InstallSurfaceObservation(
            path=missing_path,
            exists=False,
            is_file=False,
            is_dir=False,
        ),
    )

    text_surface = section("project", "notes.md", preserve_user_content=True)
    text_path = Path("/observed/notes.md")
    text = f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n"

    assert install_surface_core.installed_surface_status_from_observation(
        text_surface,
        install_surface_core.InstallSurfaceObservation(
            path=text_path,
            exists=True,
            is_file=True,
            is_dir=False,
            text=text,
        ),
    )

    json_surface = InstallSurface("project", "settings.json", content_kind="json", marker="graphify")
    json_path = Path("/observed/settings.json")
    json_data = {"hooks": [{"command": "graphify query"}]}

    assert install_surface_core.installed_surface_status_from_observation(
        json_surface,
        install_surface_core.InstallSurfaceObservation(
            path=json_path,
            exists=True,
            is_file=True,
            is_dir=False,
            json_data=json_data,
            json_loaded=True,
        ),
    )


def test_json_marker_status_observation_helpers_preserve_details() -> None:
    json_surface = InstallSurface("project", "settings.json", content_kind="json", marker="graphify")

    assert install_surface_core.json_marker_status_from_observation(
        json_surface,
        install_surface_core.InstallSurfaceObservation(
            path=Path("/observed/settings.json"),
            exists=True,
            is_file=True,
            json_error_detail="invalid_json=Expecting property name enclosed in double quotes",
        ),
    ) == (False, "invalid_json=Expecting property name enclosed in double quotes")

    assert install_surface_core.json_marker_status_from_observation(
        json_surface,
        install_surface_core.InstallSurfaceObservation(
            path=Path("/observed/settings.json"),
            exists=True,
            is_file=True,
            json_error_detail="json_read_failed=permission denied",
        ),
    ) == (False, "json_read_failed=permission denied")


def test_text_marker_status_from_already_read_text_preserves_details() -> None:
    text_surface = section("project", "notes.md", preserve_user_content=True)

    assert install_surface_core.text_marker_status_from_text(
        f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n",
        text_surface,
    ) == (True, "marker_count=1; user_content_preserved; stale_replaced=True")

    assert install_surface_core.text_marker_status_from_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\nfirst\n\n{platform_specs.GRAPHIFY_MARKER}\nsecond\n",
        text_surface,
    ) == (False, "marker_count=2; user_content_missing; stale_replaced=True")

    assert install_surface_core.text_marker_status_from_text(
        f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{install_surface_core.STALE_GRAPHIFY_SENTINEL}\n",
        text_surface,
    ) == (False, "marker_count=1; user_content_preserved; stale_replaced=False")


def test_json_marker_status_from_loaded_json_facts() -> None:
    generic = InstallSurface("project", "generic.json", content_kind="json", marker="graphify")

    generic_present = json_status_from_loaded_data(generic, {"hooks": [{"command": "graphify query"}]})
    assert generic_present.ok is True
    assert generic_present.detail == "valid_json=true; schema=generic_marker; marker_present=True"

    generic_missing = json_status_from_loaded_data(generic, {"hooks": [{"command": "other"}]})
    assert generic_missing.ok is False
    assert generic_missing.detail == "valid_json=true; schema=generic_marker; marker_present=False"


def test_registered_json_expectation_status_from_loaded_json_facts() -> None:
    claude_valid = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo graphify context"}]},
                {"matcher": "Read|Glob", "hooks": [{"type": "command", "command": "echo graphify context"}]},
            ]
        }
    }
    assert registered_json_status("claude", "project", ".claude/settings.json", claude_valid).ok is True
    assert registered_json_status("codebuddy", "project", ".codebuddy/settings.json", {"note": "graphify in wrong location"}).ok is False

    codex_valid = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/tmp/bin/graphify hook-check"}]}]}}
    assert registered_json_status("codex", "project", ".codex/hooks.json", codex_valid).ok is True
    assert registered_json_status("codex", "project", ".codex/hooks.json", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "graphify query"}]}]}}).ok is False

    gemini_valid = {"hooks": {"BeforeTool": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "python -c 'print(\"graphify\")'"}]}]}}
    assert registered_json_status("gemini", "project", ".gemini/settings.json", gemini_valid).ok is True
    assert registered_json_status("gemini", "project", ".gemini/settings.json", {"hooks": {"PreToolUse": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "graphify"}]}]}}).ok is False

    assert registered_json_status("kilo", "project", ".kilo/kilo.json", {"plugin": ["file:///tmp/project/.kilo/plugins/graphify.js"]}).ok is True
    assert registered_json_status("kilo", "project", ".kilo/kilo.json", {"plugin": ["graphify"]}).ok is False
    assert registered_json_status("opencode", "project", ".opencode/opencode.json", {"plugin": [".opencode/plugins/graphify.js"]}).ok is True
    assert registered_json_status("opencode", "project", ".opencode/opencode.json", {"plugin": ["file:///tmp/project/.opencode/plugins/graphify.js"]}).ok is False


def test_install_surface_core_decides_uninstalled_status_from_observed_facts() -> None:
    plain = InstallSurface("project", "plain.txt")

    removed_status = install_surface_core.uninstalled_surface_status_from_observation(
        plain,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/plain.txt"),
            exists=False,
        ),
    )

    assert removed_status == install_surface_core.InstallSurfaceStatus(
        Path("/observed/plain.txt"),
        ok=True,
        detail="removed",
    )

    still_exists_status = install_surface_core.uninstalled_surface_status_from_observation(
        plain,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/plain.txt"),
            exists=True,
            is_file=True,
            text="still here\n",
        ),
    )

    assert still_exists_status.ok is False
    assert still_exists_status.detail == "still_exists"

    preserved_text = section("project", "notes.md", preserve_user_content=True)
    preserved_status = install_surface_core.uninstalled_surface_status_from_observation(
        preserved_text,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/notes.md"),
            exists=True,
            is_file=True,
            text=f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n## User Section\n",
        ),
    )

    assert preserved_status.ok is True
    assert preserved_status.detail == "graphify_removed=True; user_content_preserved=True"

    stale_status = install_surface_core.uninstalled_surface_status_from_observation(
        preserved_text,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/notes.md"),
            exists=True,
            is_file=True,
            text=f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{install_surface_core.STALE_GRAPHIFY_SENTINEL}\n",
        ),
    )

    assert stale_status.ok is False
    assert stale_status.detail == "graphify_removed=False; user_content_preserved=True"

    missing_user_content_status = install_surface_core.uninstalled_surface_status_from_observation(
        preserved_text,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/notes.md"),
            exists=False,
        ),
    )

    assert missing_user_content_status.ok is False
    assert missing_user_content_status.detail == "user_content_file_missing"

    read_error_status = install_surface_core.uninstalled_surface_status_from_observation(
        preserved_text,
        install_surface_core.UninstallSurfaceObservation(
            path=Path("/observed/notes.md"),
            exists=True,
            is_file=True,
            text_error_detail="text_read_failed=permission denied",
        ),
    )

    assert read_error_status.ok is False
    assert read_error_status.detail == "text_read_failed=permission denied"


def test_uninstalled_surface_status_observation_helper_preserves_paths_and_details() -> None:
    plain = InstallSurface("project", "plain.txt")
    plain_path = Path("/observed/plain.txt")

    assert install_surface_core.uninstalled_surface_status_from_observation(
        plain,
        install_surface_core.UninstallSurfaceObservation(
            path=plain_path,
            exists=False,
            is_file=False,
            is_dir=False,
        ),
    )

    text_section = section("project", "notes.md", preserve_user_content=True)
    notes_path = Path("/observed/notes.md")
    preserved_text = f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n## User Section\n"

    assert install_surface_core.uninstalled_surface_status_from_observation(
        text_section,
        install_surface_core.UninstallSurfaceObservation(
            path=notes_path,
            exists=True,
            is_file=True,
            is_dir=False,
            text=preserved_text,
        ),
    )

    stale_text = f"# Notes\n\n{install_surface_core.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{install_surface_core.STALE_GRAPHIFY_SENTINEL}\n"

    assert install_surface_core.uninstalled_surface_status_from_observation(
        text_section,
        install_surface_core.UninstallSurfaceObservation(
            path=notes_path,
            exists=True,
            is_file=True,
            is_dir=False,
            text=stale_text,
        ),
    )
