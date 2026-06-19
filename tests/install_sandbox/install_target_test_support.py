from __future__ import annotations

from tools.install_sandbox import platform_specs


REGISTRY = platform_specs.DEFAULT_SCENARIO_REGISTRY


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
