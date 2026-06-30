from __future__ import annotations

from typing import Any

import yaml

from tools.install_sandbox.registry.spec_loader import SpecLoaderError, load_default_registry, load_registry_from_data
from tools.install_sandbox.registry.spec_normalize import normalize_registry
from tools.install_sandbox.surfaces.install_surface_models import ExpectedPath
from tools.install_sandbox.targets.install_target_defaults import DEFAULT_SCENARIO_REGISTRY
from tools.install_sandbox.targets.install_target_models import PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE, Scenario


REGISTRY = DEFAULT_SCENARIO_REGISTRY


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
                        "effects": [skill_effect_data()],
                        "uninstall_command": None,
                        "risk_notes": [PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE],
                    },
                    "project": {
                        "effects": [
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
    for target_name, target_data in data["platforms"].items():
        (path / f"{target_name}.yaml").write_text(yaml.safe_dump(target_data, sort_keys=False), encoding="utf-8")


def scenario_for(target_name: str, scope: str) -> Scenario:
    scenario = REGISTRY.make_scenario(target_name, scope)
    assert scenario is not None
    return scenario


def expected_entry(target_name: str, scope: str, root: str, relative: str) -> ExpectedPath:
    scenario = scenario_for(target_name, scope)
    return next(entry for entry in scenario.expected if entry.root == root and entry.relative == relative)


def scenario_entries() -> list[tuple[str, str, Scenario, ExpectedPath]]:
    entries: list[tuple[str, str, Scenario, ExpectedPath]] = []
    for target_name in REGISTRY.target_names:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(target_name, scope)
            if scenario is None:
                continue
            entries.extend((target_name, scope, scenario, entry) for entry in scenario.expected)
    return entries


def entry_id(target_name: str, scope: str, entry: ExpectedPath) -> tuple[str, str, str, str]:
    return target_name, scope, entry.root, entry.relative
