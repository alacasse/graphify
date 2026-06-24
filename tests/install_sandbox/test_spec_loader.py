from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from typing import Any

import pytest
import yaml

from tools.install_sandbox import install_target_catalog, platform_specs, spec_loader
from tools.install_sandbox.spec_normalize import normalize_registry
from tools.install_sandbox.spec_loader import SpecLoaderError, load_default_registry, load_registry_from_data, load_registry_from_dir


FIELD_CLASS_DURABLE_TARGET_FACT = "durable_target_fact"
FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION = "transitional_sandbox_execution_data"
FIELD_CLASS_DERIVED_DEFAULT = "derived_default"
FIELD_CLASS_HARNESS_POLICY = "harness_policy"
FIELD_CLASS_RUNTIME_LIMITATION = "runtime_limitation"
MIGRATED_EFFECTS_SPECS = {"aider", "amp", "codebuddy", "codex", "gemini", "hermes"}


def _skill(relative: str = ".mini/skills/graphify/SKILL.md") -> dict[str, object]:
    return {"root": "home", "relative": relative}


def _valid_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "platforms": {
            "mini": {
                "user_skill": ".mini/skills/graphify/SKILL.md",
                "project_skill": ".mini/skills/graphify/SKILL.md",
                "scopes": {
                    "user": {
                        "expected": [_skill()],
                        "uninstall_command": None,
                        "risk_notes": [platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE],
                    },
                    "project": {
                        "expected": [
                            {"root": "project", "relative": ".mini/skills/graphify/SKILL.md"},
                            {"kind": "text_section", "root": "project", "relative": "AGENTS.md"},
                        ],
                        "equivalent_install_command": ["graphify", "mini", "install", "--project"],
                    },
                },
                "unsupported_scopes": {},
                "universal_uninstall_scopes": ["project"],
            }
        },
        "universal_uninstall_specs": ["project"],
        "disposable_artifact_specs": [
            {
                "scenario_id": "purge-disposable-graphify-out",
                "platform_label": "purge",
                "scope": "project",
                "command": ["graphify", "uninstall", "--purge"],
                "cwd_root": "project",
                "artifact_subdir": "uninstall-purge",
                "disposable_path_root": "project",
                "disposable_path_relative": "graphify-out",
                "seed_files": [{"relative": "graph.json", "content": "{}\n"}],
                "scope_eligibility": ["project", "both"],
                "risk_note": "synthetic disposable artifact policy",
            }
        ],
    }


def _default_scope_effect_key_inventory() -> dict[str, set[str]]:
    inventory = {"expected": set(), "effects": set(), "missing": set(), "mixed": set()}
    for path in sorted(spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")):
        if path.name == "shared.yaml":
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for scope_name, scope_data in data.get("scopes", {}).items():
            scope_id = f"{path.stem}.{scope_name}"
            has_expected = "expected" in scope_data
            has_effects = "effects" in scope_data
            if has_expected and has_effects:
                inventory["mixed"].add(scope_id)
            elif has_effects:
                inventory["effects"].add(scope_id)
            elif has_expected:
                inventory["expected"].add(scope_id)
            else:
                inventory["missing"].add(scope_id)
    return inventory


def test_loader_returns_existing_registry_dataclasses_with_defaults() -> None:
    registry = load_registry_from_data(_valid_data())
    user = registry.make_scenario("mini", "user")
    project = registry.make_scenario("mini", "project")
    spec = registry.platform_spec("mini")

    assert isinstance(registry, platform_specs.ScenarioRegistry)
    assert isinstance(spec, platform_specs.PlatformSpec)
    assert spec.display_name is None
    assert spec.target_kind == "product"
    assert user is not None
    assert user.install_command == ("graphify", "install", "--platform", "mini")
    assert user.uninstall_command is None
    assert user.cwd_root == "user_cwd"
    assert user.allowed_roots == ("home",)
    assert isinstance(user.expected[0], platform_specs.SkillEffect)
    assert user.expected[0].skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert project is not None
    assert registry.install_variants(project) == (
        platform_specs.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "mini")),
        platform_specs.InstallCommandVariant("direct", ("graphify", "mini", "install", "--project")),
    )
    agents = next(entry for entry in project.expected if entry.relative == "AGENTS.md")
    assert isinstance(agents, platform_specs.TextSectionEffect)
    assert agents.text_expectation.preserve_user_content
    assert agents.text_expectation.require_user_content_on_uninstall
    assert registry.universal_uninstall_specs[0].scenario_id == "universal-uninstall-project"


def test_loader_preserves_explicit_target_metadata() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["display_name"] = "Mini Target"
    data["platforms"]["mini"]["target_kind"] = "generic_standard"

    spec = load_registry_from_data(data).platform_spec("mini")

    assert spec.display_name == "Mini Target"
    assert spec.target_kind == "generic_standard"


def test_loader_derives_conventional_product_yaml_equivalent_to_explicit_fixture() -> None:
    explicit = _valid_data()
    conventional = deepcopy(_valid_data())
    mini = conventional["platforms"]["mini"]
    mini.pop("user_skill")
    mini.pop("project_skill")
    mini["scopes"]["user"].pop("risk_notes")
    mini["scopes"]["project"].pop("equivalent_install_command")

    assert FIELD_CLASS_DERIVED_DEFAULT == "derived_default"
    assert normalize_registry(load_registry_from_data(conventional)) == normalize_registry(load_registry_from_data(explicit))


def test_default_registry_spec_weight_fields_are_classified() -> None:
    candidate_fields = {
        "install_command",
        "uninstall_command",
        "equivalent_install_command",
        "universal_uninstall_scopes",
        "unsupported_scopes",
        "simulated_linux_layout",
        "reference_bundles",
        "target_runtime_validation",
    }
    expected_classification = {
        "install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "uninstall_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "equivalent_install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "universal_uninstall_scopes": FIELD_CLASS_HARNESS_POLICY,
        "unsupported_scopes": FIELD_CLASS_RUNTIME_LIMITATION,
        "simulated_linux_layout": FIELD_CLASS_RUNTIME_LIMITATION,
        "reference_bundles": FIELD_CLASS_DURABLE_TARGET_FACT,
        "target_runtime_validation": FIELD_CLASS_RUNTIME_LIMITATION,
    }
    expected_inventory = {
        "install_command": {
            "antigravity.user",
            "cursor.project",
            "kilo.project",
            "kiro.project",
            "vscode.project",
            "vscode.user",
        },
        "uninstall_command": {
            "agents.user",
            "aider.user",
            "amp.user",
            "antigravity-windows.user",
            "antigravity.user",
            "claude.user",
            "claw.user",
            "codebuddy.user",
            "codex.user",
            "copilot.user",
            "cursor.project",
            "devin.user",
            "droid.user",
            "gemini.user",
            "hermes.user",
            "kilo.project",
            "kilo.user",
            "kimi.user",
            "kiro.project",
            "kiro.user",
            "opencode.user",
            "pi.user",
            "trae-cn.user",
            "trae.user",
            "vscode.project",
            "vscode.user",
            "windows.user",
        },
        "equivalent_install_command": {
            "antigravity-windows.project",
            "antigravity.project",
            "codebuddy.project",
            "copilot.user",
            "cursor.project",
            "devin.project",
            "devin.user",
            "gemini.user",
            "kimi.project",
            "kiro.project",
            "pi.project",
            "pi.user",
            "windows.project",
        },
        "universal_uninstall_scopes": {
            "antigravity",
            "claude",
            "codebuddy",
            "codex",
            "cursor",
            "devin",
            "gemini",
            "vscode",
        },
        "unsupported_scopes": {"cursor"},
        "simulated_linux_layout": {"antigravity-windows", "windows"},
        "reference_bundles": {"vscode"},
        "target_runtime_validation": set(),
    }
    actual_inventory = {field: set() for field in candidate_fields}

    for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for field in candidate_fields & data.keys():
            actual_inventory[field].add(path.stem)
        for scope_name, scope_data in data.get("scopes", {}).items():
            for field in candidate_fields & scope_data.keys():
                actual_inventory[field].add(f"{path.stem}.{scope_name}")

    assert actual_inventory == expected_inventory
    assert set(expected_classification) == candidate_fields
    assert expected_classification["universal_uninstall_scopes"] == FIELD_CLASS_HARNESS_POLICY


def test_default_registry_explicit_project_equivalent_nulls_are_meaningful_runtime_limitations(tmp_path: Any) -> None:
    for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        project_scope = data.get("scopes", {}).get("project")
        if isinstance(project_scope, dict) and project_scope.get("equivalent_install_command", "missing") is None:
            registry_dir = tmp_path / path.stem
            registry_dir.mkdir()
            _write_registry_dir(registry_dir, {"platforms": {path.stem: data}})
            explicit = load_registry_from_dir(registry_dir)
            explicit_project = explicit.platform_spec(path.stem).scopes["project"]

            project_scope.pop("equivalent_install_command")
            _write_registry_dir(registry_dir, {"platforms": {path.stem: data}})
            derived = load_registry_from_dir(registry_dir)
            derived_project = derived.platform_spec(path.stem).scopes["project"]

            assert explicit_project.equivalent_install_command is None
            assert derived_project.equivalent_install_command == ("graphify", path.stem, "install", "--project")
            assert normalize_registry(explicit) != normalize_registry(derived)


def test_loader_accepts_effects_key_equivalent_to_expected() -> None:
    expected_data = _valid_data()
    effects_data = deepcopy(expected_data)
    for scope in effects_data["platforms"]["mini"]["scopes"].values():
        scope["effects"] = scope.pop("expected")

    assert normalize_registry(load_registry_from_data(effects_data)) == normalize_registry(load_registry_from_data(expected_data))


def test_loader_rejects_scope_with_expected_and_effects() -> None:
    data = _valid_data()
    user_scope = data["platforms"]["mini"]["scopes"]["user"]
    user_scope["effects"] = deepcopy(user_scope["expected"])

    _expect_invalid(data, "declare only one of expected or effects")


def test_loader_rejects_scope_without_expected_or_effects() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"].pop("expected")

    _expect_invalid(data, "runnable scope must declare expected or effects")


def test_default_registry_runnable_scopes_declare_one_effect_vocabulary_key() -> None:
    inventory = _default_scope_effect_key_inventory()

    assert inventory["mixed"] == set()
    assert inventory["missing"] == set()
    assert inventory["effects"]
    assert inventory["expected"]


def test_default_registry_effects_migration_inventory_is_explicit() -> None:
    inventory = _default_scope_effect_key_inventory()
    migrated_specs = {scope_id.split(".", maxsplit=1)[0] for scope_id in inventory["effects"]}
    legacy_specs = {scope_id.split(".", maxsplit=1)[0] for scope_id in inventory["expected"]}
    all_specs = {
        path.stem
        for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")
        if path.name != "shared.yaml"
    }

    assert migrated_specs == MIGRATED_EFFECTS_SPECS
    assert legacy_specs == all_specs - MIGRATED_EFFECTS_SPECS
    assert legacy_specs


def test_loader_preserves_explicit_no_project_install_equivalence() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["project"]["equivalent_install_command"] = None

    registry = load_registry_from_data(data)
    project = registry.make_scenario("mini", "project")

    assert project is not None
    assert registry.equivalent_install_command(project) is None


def _write_registry_dir(path: Any, data: dict[str, Any]) -> None:
    for platform_name, platform_data in data["platforms"].items():
        (path / f"{platform_name}.yaml").write_text(yaml.safe_dump(platform_data, sort_keys=False), encoding="utf-8")


def test_default_registry_loads_and_returns_scenario_registry() -> None:
    registry = load_default_registry()

    assert isinstance(registry, platform_specs.ScenarioRegistry)
    assert isinstance(registry, install_target_catalog.ScenarioRegistry)
    assert type(registry) is install_target_catalog.InstallTargetCatalog
    assert install_target_catalog.InstallTargetCatalog is install_target_catalog.ScenarioRegistry
    assert registry.specs
    assert registry.universal_uninstall_specs == ()
    assert registry.disposable_artifact_specs == ()


@pytest.mark.parametrize("spec_name", sorted(MIGRATED_EFFECTS_SPECS))
def test_default_registry_migrated_yaml_uses_effects_key_for_runnable_scopes(spec_name: str) -> None:
    data = yaml.safe_load((spec_loader.DEFAULT_REGISTRY_PATH / f"{spec_name}.yaml").read_text(encoding="utf-8"))

    assert set(data["scopes"]) == {"user", "project"}
    for scope in data["scopes"].values():
        assert "effects" in scope
        assert "expected" not in scope


def test_spec_loader_uses_catalog_import_surface() -> None:
    assert spec_loader.ScenarioRegistry is install_target_catalog.ScenarioRegistry
    assert spec_loader.InstallTargetCatalog is install_target_catalog.InstallTargetCatalog
    assert spec_loader._scenario is install_target_catalog._scenario


def test_spec_loader_can_be_imported_without_platform_specs_first() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from tools.install_sandbox.spec_loader import load_registry_from_yaml; "
                "print(load_registry_from_yaml.__name__); "
                "print('tools.install_sandbox.platform_specs' in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["load_registry_from_yaml", "False"]


def test_default_registry_discovers_product_yaml_files_in_filename_order() -> None:
    registry = load_default_registry()
    expected = sorted(
        product_path.stem
        for product_path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")
        if product_path.name != "shared.yaml"
    )

    assert registry.platform_names == expected


def test_load_registry_from_dir_does_not_supply_synthetic_registry_policies(tmp_path: Any) -> None:
    data = _valid_data()
    data["platforms"]["mini"]["simulated_linux_layout"] = True
    _write_registry_dir(tmp_path, data)

    registry = load_registry_from_dir(tmp_path)

    assert registry.universal_uninstall_specs == ()
    assert registry.disposable_artifact_specs == ()
    assert registry.platform_spec("mini").target_runtime_validation == ()


def test_load_registry_from_dir_rejects_empty_product_specs(tmp_path: Any) -> None:
    data = _valid_data()
    _write_registry_dir(tmp_path, data)
    (tmp_path / "mini.yaml").unlink()

    with pytest.raises(SpecLoaderError, match="expected at least one platform spec file"):
        load_registry_from_dir(tmp_path)


def test_load_registry_from_dir_discovers_added_product_yaml_files(tmp_path: Any) -> None:
    data = _valid_data()
    _write_registry_dir(tmp_path, data)
    (tmp_path / "alpha.yaml").write_text(yaml.safe_dump(deepcopy(data["platforms"]["mini"]), sort_keys=False), encoding="utf-8")

    registry = load_registry_from_dir(tmp_path)

    assert registry.platform_names == ["alpha", "mini"]


def test_load_registry_from_dir_rejects_filename_key_mismatch(tmp_path: Any) -> None:
    data = _valid_data()
    data["platforms"]["mini"]["name"] = "other"
    _write_registry_dir(tmp_path, data)

    with pytest.raises(SpecLoaderError, match="platform key/name mismatch: mini != other"):
        load_registry_from_dir(tmp_path)


def test_load_registry_from_dir_uses_deterministic_filename_order(tmp_path: Any) -> None:
    data = _valid_data()
    mini = deepcopy(data["platforms"]["mini"])
    data["platforms"] = {
        "beta": deepcopy(mini),
        "alpha": deepcopy(mini),
    }
    _write_registry_dir(tmp_path, data)

    registry = load_registry_from_dir(tmp_path)

    assert registry.platform_names == ["alpha", "beta"]


def test_load_registry_from_dir_ignores_shared_yaml_and_orders_by_filename_stem(
    tmp_path: Any,
) -> None:
    data = _valid_data()
    mini = deepcopy(data["platforms"]["mini"])
    (tmp_path / "beta.yaml").write_text(yaml.safe_dump(mini, sort_keys=False), encoding="utf-8")
    (tmp_path / "alpha.yaml").write_text(yaml.safe_dump(mini, sort_keys=False), encoding="utf-8")
    (tmp_path / "shared.yaml").write_text(
        yaml.safe_dump({"not": "a platform spec"}, sort_keys=False),
        encoding="utf-8",
    )

    registry = load_registry_from_dir(tmp_path)

    assert registry.platform_names == ["alpha", "beta"]


def test_default_registry_every_scope_is_runnable_or_explained() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            runnable = registry.make_scenario(platform_name, scope) is not None
            explained = registry.unsupported_scope_reason(platform_name, scope) is not None
            assert runnable != explained, f"{platform_name}/{scope} must be runnable xor explained"


def test_default_registry_skill_effects_declare_sidecar_expectation() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            scenario = registry.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            for entry in scenario.expected:
                if entry.relative.endswith("SKILL.md"):
                    assert entry.skill_sidecar_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"


def _expect_invalid(data: dict[str, Any], match: str) -> None:
    with pytest.raises(SpecLoaderError, match=match):
        load_registry_from_data(data)


def test_loader_rejects_unknown_expected_root() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["root"] = "repo_mount"

    _expect_invalid(data, "unknown expected root")


def test_loader_rejects_platform_key_name_mismatch() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["name"] = "other"

    _expect_invalid(data, "platform key/name mismatch")


def test_loader_rejects_missing_or_conflicting_scope_declarations() -> None:
    missing = _valid_data()
    missing["platforms"]["mini"]["scopes"].pop("project")
    _expect_invalid(missing, "exactly one runnable scope")

    conflicting = _valid_data()
    conflicting["platforms"]["mini"]["unsupported_scopes"]["project"] = "unsupported"
    _expect_invalid(conflicting, "exactly one runnable scope")


def test_loader_rejects_invalid_commands() -> None:
    empty = _valid_data()
    empty["platforms"]["mini"]["scopes"]["user"]["install_command"] = []
    _expect_invalid(empty, "expected non-empty list")

    non_string = _valid_data()
    non_string["platforms"]["mini"]["scopes"]["user"]["install_command"] = ["tool", 3]
    _expect_invalid(non_string, "expected non-empty string")


def test_loader_rejects_invalid_relative_paths() -> None:
    absolute = _valid_data()
    absolute["platforms"]["mini"]["scopes"]["user"]["expected"][0]["relative"] = "/tmp/SKILL.md"
    _expect_invalid(absolute, "must not be absolute")

    escaping = _valid_data()
    escaping["platforms"]["mini"]["scopes"]["user"]["expected"][0]["relative"] = "../SKILL.md"
    _expect_invalid(escaping, "must not escape")


def test_loader_rejects_duplicate_install_variant_labels() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["project"]["install_variants"] = [
        {"label": "same", "command": ["tool", "a"]},
        {"label": "same", "command": ["tool", "b"]},
    ]

    _expect_invalid(data, "duplicate install variant label")


def test_loader_rejects_invalid_scope_names() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["both"] = data["platforms"]["mini"]["scopes"].pop("project")

    _expect_invalid(data, "invalid platform scope: both")


def test_loader_derives_skill_sidecar_kind_and_rejects_explicit_wrong_kind() -> None:
    derived = load_registry_from_data(_valid_data()).make_scenario("mini", "user")
    assert derived is not None
    assert isinstance(derived.expected[0], platform_specs.SkillEffect)
    assert derived.expected[0].skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()

    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "file"

    _expect_invalid(data, "SKILL.md effects must use kind: skill or omit kind")


def test_loader_derives_plain_file_effect_from_non_skill_relative_path() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"root": "home", "relative": ".mini/config.toml", "remove_on_uninstall": False}
    ]

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    effect = user.expected[0]
    assert isinstance(effect, platform_specs.FileEffect)
    assert not isinstance(effect, platform_specs.SkillEffect)
    assert effect.root == "home"
    assert effect.relative == ".mini/config.toml"
    assert effect.content_kind == "text"
    assert effect.marker is None
    assert effect.remove_on_uninstall is False


def test_loader_rejects_removed_plugin_file_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0] = {"kind": "plugin_file", "root": "home", "relative": ".mini/plugins/graphify.js"}

    _expect_invalid(data, "unknown effect kind")


def test_loader_rejects_unknown_effect_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "mystery"

    _expect_invalid(data, "unknown effect kind")


def test_loader_derives_json_hook_detail_names() -> None:
    single = _valid_data()
    single["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"kind": "json_hooks", "root": "home", "relative": ".mini/settings.json", "schema_name": "mini_settings", "hooks": [{"event": "PreToolUse", "matcher": "Bash"}]}
    ]
    single_scenario = load_registry_from_data(single).make_scenario("mini", "user")
    assert single_scenario is not None
    assert isinstance(single_scenario.expected[0], platform_specs.JsonHooksEffect)
    single_json = single_scenario.expected[0].json_expectation
    assert single_json is not None
    assert single_json.hooks[0].detail_name == "graphify_hook_present"

    multiple = _valid_data()
    multiple["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {
            "kind": "json_hooks",
            "root": "home",
            "relative": ".mini/settings.json",
            "schema_name": "mini_settings",
            "hooks": [
                {"event": "PreToolUse", "matcher": "Bash"},
                {"event": "PreToolUse", "matcher": "Read|Glob"},
            ],
        }
    ]
    multiple_scenario = load_registry_from_data(multiple).make_scenario("mini", "user")
    assert multiple_scenario is not None
    multiple_json = multiple_scenario.expected[0].json_expectation
    assert multiple_json is not None
    assert [hook.detail_name for hook in multiple_json.hooks] == ["bash_hook_present", "read_glob_hook_present"]


def test_loader_derives_json_plugin_relative_from_paired_payload() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"root": "home", "relative": ".mini/plugins/graphify.js"},
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]

    scenario = load_registry_from_data(data).make_scenario("mini", "user")

    assert scenario is not None
    assert isinstance(next(entry for entry in scenario.expected if entry.relative == ".mini/plugins/graphify.js"), platform_specs.FileEffect)
    config = next(entry for entry in scenario.expected if entry.relative == ".mini/config.json")
    assert isinstance(config, platform_specs.JsonPluginEffect)
    assert config.json_expectation is not None
    assert config.json_expectation.plugin is not None
    assert config.json_expectation.plugin.expected_entry == ".mini/plugins/graphify.js"


def test_loader_rejects_unpaired_or_ambiguous_json_plugin_payloads() -> None:
    missing_plugin = _valid_data()
    missing_plugin["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]
    _expect_invalid(missing_plugin, "one paired JavaScript plugin payload")

    ambiguous_plugin = _valid_data()
    ambiguous_plugin["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"root": "home", "relative": ".mini/plugins/graphify.js"},
        {"root": "home", "relative": ".mini/plugins/extra.js"},
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]
    _expect_invalid(ambiguous_plugin, "ambiguous paired JavaScript plugin payloads")


def test_loader_derives_text_section_policies() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"kind": "text_section", "root": "home", "relative": ".claude/CLAUDE.md", "marker": "# graphify"},
    ]

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    instruction = next(entry for entry in user.expected if entry.relative == ".claude/CLAUDE.md")
    assert instruction.text_expectation.preserve_user_content
    assert not instruction.text_expectation.repair_stale_graphify_section
    assert not instruction.remove_on_uninstall


def test_loader_derives_scope_locality_and_simulated_notes() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["simulated_linux_layout"] = True
    data["platforms"]["mini"]["scopes"]["user"]["expected"].append({"root": "user_cwd", "relative": "GEMINI.md", "kind": "text_section"})

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    assert user.allowed_roots == ("home", "project", "user_cwd")
    assert user.risk_notes == (
        platform_specs.MIXED_SCOPE_PROJECT_WIRING_NOTE,
        platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        platform_specs.SIMULATED_LINUX_LAYOUT_NOTE,
    )


def test_loader_preserves_explicit_target_runtime_validation() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["target_runtime_validation"] = [
        {
            "section_title": "Windows Validation",
            "status": "payload_consistency_only",
            "strategy": "payload check only",
            "targets": ["windows payload"],
            "notes": ["runtime validation is external"],
        }
    ]
    data["platforms"]["mini"]["simulated_linux_layout"] = True

    spec = load_registry_from_data(data).platform_spec("mini")

    assert spec.target_runtime_validation == (
        platform_specs.TargetRuntimeValidationSpec(
            section_title="Windows Validation",
            status="payload_consistency_only",
            strategy="payload check only",
            targets=("windows payload",),
            notes=("runtime validation is external",),
        ),
    )


def test_loader_ignores_top_level_runtime_validation_policies() -> None:
    data = _valid_data()
    data["target_runtime_validation_policies"] = {"typo": {}}

    assert load_registry_from_data(data).platform_spec("mini").target_runtime_validation == ()


def test_loader_rejects_unknown_structured_risk_note() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["risk_notes"] = ["unknown_structured_note"]

    _expect_invalid(data, "unknown structured risk note")


def test_load_registry_from_data_uses_platform_mapping_order() -> None:
    data = deepcopy(_valid_data())
    mini = deepcopy(data["platforms"]["mini"])
    data["platforms"] = {
        "zeta": deepcopy(mini),
        "alpha": deepcopy(mini),
    }

    registry = load_registry_from_data(data)

    assert registry.platform_names == ["zeta", "alpha"]
