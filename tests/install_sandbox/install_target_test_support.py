from __future__ import annotations

from typing import Any

import yaml

from tools.install_sandbox import platform_specs
from tools.install_sandbox.spec_loader import SpecLoaderError, load_default_registry, load_registry_from_data
from tools.install_sandbox.spec_normalize import normalize_registry


REGISTRY = platform_specs.DEFAULT_SCENARIO_REGISTRY


def normalize_default_registry() -> dict[str, object]:
    return normalize_registry(load_default_registry())


def skill_effect_data(relative: str = ".mini/skills/graphify/SKILL.md") -> dict[str, object]:
    return {"root": "home", "relative": relative}


def valid_registry_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "platforms": {
            "mini": {
                "user_skill": ".mini/skills/graphify/SKILL.md",
                "project_skill": ".mini/skills/graphify/SKILL.md",
                "scopes": {
                    "user": {
                        "expected": [skill_effect_data()],
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


def expect_invalid_registry(data: dict[str, Any], match: str) -> None:
    import pytest

    with pytest.raises(SpecLoaderError, match=match):
        load_registry_from_data(data)


def write_registry_dir(path: Any, data: dict[str, Any]) -> None:
    for platform_name, platform_data in data["platforms"].items():
        (path / f"{platform_name}.yaml").write_text(yaml.safe_dump(platform_data, sort_keys=False), encoding="utf-8")


def scenario_for(platform_name: str, scope: str) -> platform_specs.Scenario:
    scenario = REGISTRY.make_scenario(platform_name, scope)
    assert scenario is not None
    return scenario


def expected_entry(platform_name: str, scope: str, root: str, relative: str) -> platform_specs.ExpectedPath:
    scenario = scenario_for(platform_name, scope)
    return next(entry for entry in scenario.expected if entry.root == root and entry.relative == relative)


def scenario_entries() -> list[tuple[str, str, platform_specs.Scenario, platform_specs.ExpectedPath]]:
    entries: list[tuple[str, str, platform_specs.Scenario, platform_specs.ExpectedPath]] = []
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            entries.extend((platform_name, scope, scenario, entry) for entry in scenario.expected)
    return entries


def entry_id(platform_name: str, scope: str, entry: platform_specs.ExpectedPath) -> tuple[str, str, str, str]:
    return platform_name, scope, entry.root, entry.relative
