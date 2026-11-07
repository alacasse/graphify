"""Build controlled grouped runs through the campaign's normal YAML entry point."""

import json
from pathlib import Path

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.host.campaign_definition import load_campaign_definition


def grouped_cases(
    root: Path, manifest: Path, removal: tuple[str, ...]
) -> tuple[EffectInstallCase, ...]:
    context = {
        "identity": "controlled-group",
        "version_source": "METADATA",
        "rules": {
            "hook_timeout": 10,
            "skill_lock": "persistent",
            "json_backup": ".graphify-bak",
            "skill_backup": ".bak",
            "json_registry": False,
        },
        "uninstall_invocation": list(removal),
    }
    if removal == ("uninstall",):
        context["purge_invocation"] = ["uninstall", "--purge"]
    context_file = root / "context.json"
    context_file.write_text(json.dumps(context))
    return load_campaign_definition(
        spec_file=manifest,
        subject_context_file=context_file,
        subject_checkout=root / "subject",
    ).built.cases
