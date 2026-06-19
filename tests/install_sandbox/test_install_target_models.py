from __future__ import annotations

from graphify import __main__ as graphify_main

from tools.install_sandbox import install_target_models, platform_specs

from install_target_test_support import REGISTRY, entry_id, scenario_entries

USER_OWNED_TEXT_SECTION_RELATIVES = {
    ".claude/CLAUDE.md",
    ".github/copilot-instructions.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
}


def test_expected_path_manifest_logic() -> None:
    user = REGISTRY.make_scenario("codex", "user")
    project = REGISTRY.make_scenario("codex", "project")
    assert user is not None
    assert project is not None
    assert any(entry.root == "home" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in user.expected)
    assert any(entry.root == "project" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in project.expected)
    assert any(entry.root == "project" and entry.relative == ".codex/hooks.json" for entry in project.expected)

    codebuddy = REGISTRY.make_scenario("codebuddy", "project")
    assert codebuddy is not None
    assert any(entry.relative == "CODEBUDDY.md" for entry in codebuddy.expected)
    assert any(entry.relative == ".codebuddy/settings.json" for entry in codebuddy.expected)


def test_json_effects_declare_behavior_expectations() -> None:
    for platform_name, scope, scenario, entry in scenario_entries():
        if entry.content_kind != "json":
            continue

        assert entry.content_kind == "json"
        assert entry.marker == "graphify"
        assert entry.json_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"
        assert entry.json_expectation.schema_name
        has_hooks = bool(entry.json_expectation.hooks)
        has_plugin = entry.json_expectation.plugin is not None
        assert has_hooks != has_plugin, f"{platform_name}/{scope}/{entry.relative}"
        if has_plugin:
            plugin = entry.json_expectation.plugin
            assert plugin is not None
            assert any(
                candidate.root == entry.root and candidate.relative == plugin.expected_entry
                for candidate in scenario.expected
            ), f"{platform_name}/{scope}/{entry.relative}"


def test_json_schema_names_follow_file_surface_conventions() -> None:
    for platform_name, scope, _, entry in scenario_entries():
        if entry.content_kind != "json":
            continue

        assert entry.json_expectation is not None
        directory = entry.relative.split("/", maxsplit=1)[0].lstrip(".")
        filename = entry.relative.rsplit("/", maxsplit=1)[-1]
        stem = filename.removesuffix(".json")
        if stem in {"hooks", "settings"}:
            expected_schema = f"{directory}_{stem}"
        else:
            expected_schema = f"{stem}_config"
        assert entry.json_expectation.schema_name == expected_schema, f"{platform_name}/{scope}/{entry.relative}"


def test_text_section_user_content_policy_follows_instruction_file_conventions() -> None:
    for platform_name, scope, _, entry in scenario_entries():
        if entry.content_kind != "text" or entry.marker is None:
            continue

        should_preserve = entry.relative in USER_OWNED_TEXT_SECTION_RELATIVES
        assert entry.text_expectation.preserve_user_content is should_preserve, f"{platform_name}/{scope}/{entry.relative}"
        assert entry.text_expectation.require_user_content_on_uninstall is should_preserve, f"{platform_name}/{scope}/{entry.relative}"


def test_text_section_repair_policy_matches_marker_ownership() -> None:
    for platform_name, scope, _, entry in scenario_entries():
        if entry.content_kind != "text" or entry.marker is None:
            continue

        assert entry.text_expectation.repair_stale_graphify_section is (
            entry.marker == install_target_models.GRAPHIFY_MARKER
        ), f"{platform_name}/{scope}/{entry.relative}"


def test_claude_instruction_docs_use_legacy_hash_marker_and_removal_policy() -> None:
    claude_instruction_entries = {
        entry_id(platform_name, scope, entry): entry
        for platform_name, scope, _, entry in scenario_entries()
        if entry.relative == ".claude/CLAUDE.md"
    }

    assert set(claude_instruction_entries) == {
        ("claude", "user", "home", ".claude/CLAUDE.md"),
        ("claude", "project", "project", ".claude/CLAUDE.md"),
        ("windows", "user", "home", ".claude/CLAUDE.md"),
        ("windows", "project", "project", ".claude/CLAUDE.md"),
    }
    for (platform_name, scope, root, relative), entry in claude_instruction_entries.items():
        assert entry.marker == "# graphify", f"{platform_name}/{scope}/{relative}"
        assert not entry.text_expectation.repair_stale_graphify_section
        assert entry.remove_on_uninstall is not (root == "home"), f"{platform_name}/{scope}/{relative}"


def test_kiro_steering_doc_uses_product_native_graphify_marker() -> None:
    kiro_marker_entries = {
        entry_id(platform_name, scope, entry): entry
        for platform_name, scope, _, entry in scenario_entries()
        if entry.marker == "graphify:"
    }

    assert set(kiro_marker_entries) == {
        ("kiro", "project", "project", ".kiro/steering/graphify.md"),
    }
    for entry in kiro_marker_entries.values():
        assert not entry.text_expectation.repair_stale_graphify_section
        assert entry.remove_on_uninstall


def test_only_home_claude_instruction_docs_are_left_after_uninstall() -> None:
    non_removable_entries = {
        entry_id(platform_name, scope, entry)
        for platform_name, scope, _, entry in scenario_entries()
        if not entry.remove_on_uninstall
    }

    assert non_removable_entries == {
        ("claude", "user", "home", ".claude/CLAUDE.md"),
        ("windows", "user", "home", ".claude/CLAUDE.md"),
    }


def test_scope_risk_notes_match_expected_root_locality() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            if scenario is None:
                continue

            roots = {entry.root for entry in scenario.expected}
            if scope == "user":
                assert (
                    install_target_models.MIXED_SCOPE_PROJECT_WIRING_NOTE in scenario.risk_notes
                ) is (not roots <= {"home"}), f"{platform_name}/{scope}"
                assert install_target_models.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE not in scenario.risk_notes
            else:
                assert (
                    install_target_models.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE in scenario.risk_notes
                ) is (not roots <= {"project"}), f"{platform_name}/{scope}"
                assert install_target_models.MIXED_SCOPE_PROJECT_WIRING_NOTE not in scenario.risk_notes


def test_user_scopes_without_uninstall_commands_declare_public_cli_risk() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        scenario = REGISTRY.make_scenario(platform_name, "user")
        if scenario is None:
            continue

        assert (
            install_target_models.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE in scenario.risk_notes
        ) is (scenario.uninstall_command is None), platform_name


def test_mixed_root_products_are_known_exceptions() -> None:
    mixed_root_scenarios = {
        (platform_name, scope): tuple(sorted({entry.root for entry in scenario.expected}))
        for platform_name in platform_specs.ALL_PLATFORMS
        for scope in ("user", "project")
        if (scenario := REGISTRY.make_scenario(platform_name, scope)) is not None
        if (scope == "user" and {entry.root for entry in scenario.expected} != {"home"})
        or (scope == "project" and {entry.root for entry in scenario.expected} != {"project"})
    }

    assert mixed_root_scenarios == {
        ("antigravity", "user"): ("home", "user_cwd"),
        ("gemini", "user"): ("home", "user_cwd"),
        ("kilo", "project"): ("home", "project"),
        ("opencode", "user"): ("home", "user_cwd"),
        ("vscode", "project"): ("home", "project"),
        ("vscode", "user"): ("home", "user_cwd"),
    }


def test_simulated_runtime_products_declare_linux_layout_limits() -> None:
    simulated_platforms = {
        platform_name
        for platform_name in platform_specs.ALL_PLATFORMS
        if REGISTRY.platform_spec(platform_name).simulated_linux_layout
    }

    assert simulated_platforms == {"antigravity-windows", "windows"}
    for platform_name in simulated_platforms:
        spec = REGISTRY.platform_spec(platform_name)
        assert spec.target_runtime_validation == ()
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            if scenario is not None:
                assert install_target_models.SIMULATED_LINUX_LAYOUT_NOTE in scenario.risk_notes


def test_skill_sidecar_policy_is_declared_on_skill_entries() -> None:
    for platform_name, scope, _, entry in scenario_entries():
        if entry.relative.endswith("SKILL.md"):
            assert entry.skill_sidecar_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"


def test_registry_mirrors_install_surface() -> None:
    cli_platforms = set(graphify_main._PLATFORM_CONFIG) | {"gemini", "cursor", "vscode"}

    assert set(platform_specs.ALL_PLATFORMS) == cli_platforms


def test_sandbox_registry_defines_all_platforms() -> None:
    specs = REGISTRY.specs

    assert list(specs) == platform_specs.ALL_PLATFORMS
    for platform_name, spec in specs.items():
        assert isinstance(spec, install_target_models.PlatformSpec)
        assert spec.name == platform_name
        assert bool(spec.scopes or spec.unsupported_scopes)


def test_vscode_reference_bundle_guard_is_declarative() -> None:
    platforms_with_reference_bundles = {
        platform_name
        for platform_name in platform_specs.ALL_PLATFORMS
        if REGISTRY.platform_spec(platform_name).reference_bundles
    }
    spec = REGISTRY.platform_spec("vscode")

    assert platforms_with_reference_bundles == {"vscode"}
    assert spec.reference_bundles == (
        install_target_models.ReferenceBundle("vscode", required_package_relative="skill-vscode.md"),
        install_target_models.ReferenceBundle("copilot"),
    )


def test_products_with_intentionally_nonstandard_skill_paths_are_known() -> None:
    nonstandard_skill_paths = {
        platform_name: (spec.user_skill, spec.project_skill)
        for platform_name in platform_specs.ALL_PLATFORMS
        if (spec := REGISTRY.platform_spec(platform_name)).user_skill != f".{platform_name}/skills/graphify/SKILL.md"
        or spec.project_skill != spec.user_skill
    }

    assert nonstandard_skill_paths == {
        "aider": (".aider/graphify/SKILL.md", ".aider/graphify/SKILL.md"),
        "amp": (".config/agents/skills/graphify/SKILL.md", ".agents/skills/graphify/SKILL.md"),
        "antigravity": (".gemini/config/skills/graphify/SKILL.md", ".agents/skills/graphify/SKILL.md"),
        "antigravity-windows": (".gemini/config/skills/graphify/SKILL.md", ".agents/skills/graphify/SKILL.md"),
        "claw": (".openclaw/skills/graphify/SKILL.md", ".openclaw/skills/graphify/SKILL.md"),
        "cursor": (None, None),
        "devin": (".config/devin/skills/graphify/SKILL.md", ".devin/skills/graphify/SKILL.md"),
        "droid": (".factory/skills/graphify/SKILL.md", ".factory/skills/graphify/SKILL.md"),
        "kilo": (".config/kilo/skills/graphify/SKILL.md", ".config/kilo/skills/graphify/SKILL.md"),
        "opencode": (".config/opencode/skills/graphify/SKILL.md", ".opencode/skills/graphify/SKILL.md"),
        "pi": (".pi/agent/skills/graphify/SKILL.md", ".pi/agent/skills/graphify/SKILL.md"),
        "vscode": (".copilot/skills/graphify/SKILL.md", None),
        "windows": (".claude/skills/graphify/SKILL.md", ".claude/skills/graphify/SKILL.md"),
    }


def test_reference_bundle_eligibility_uses_required_package_file(tmp_path) -> None:
    bundle = install_target_models.ReferenceBundle("not-vscode", required_package_relative="skill-not-vscode.md")

    assert not bundle.is_eligible(tmp_path)

    (tmp_path / "skill-not-vscode.md").write_text("skill")

    assert bundle.is_eligible(tmp_path)
    assert install_target_models.ReferenceBundle("not-vscode").is_eligible(tmp_path)


def test_codebuddy_scopes_are_runnable() -> None:
    for scope in ("user", "project"):
        scenario = REGISTRY.make_scenario("codebuddy", scope)
        assert scenario is not None
        assert any(entry.relative.endswith("SKILL.md") for entry in scenario.expected)
        assert any(entry.relative.endswith("CODEBUDDY.md") for entry in scenario.expected)
        assert any(entry.relative == ".codebuddy/settings.json" for entry in scenario.expected)
