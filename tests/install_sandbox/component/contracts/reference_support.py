"""Independent skill case and reference sources for Component tests."""

from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


def reference_case() -> EffectInstallCase:
    builds = build_effect_cases(
        EffectSpec((SkillEffect("skill.md", "refs", Destination("project", "skill")),)),
        SubjectContext(
            "synthetic",
            ("python", "installer.py"),
            "VERSION",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
    )
    return next(case for case in builds.cases if case.name == "missing-reference")


def reference_sources() -> FilesystemSnapshot:
    files = {
        ("subject", "skill.md"): b"skill",
        ("subject", "VERSION"): b"Version: 1\n",
        ("subject", "refs/z.md"): b"z",
        ("subject", "refs/a/nested.md"): b"a",
    }
    result = FilesystemSnapshot(contents=files)
    for path in ("refs", "refs/a"):
        result.entries.append(
            {"root": "subject", "path": path, "kind": "directory", "listing_complete": True}
        )
    for root, path in files:
        result.entries.append({"root": root, "path": path, "kind": "file"})
    return result
