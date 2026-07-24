from pathlib import Path

import pytest

from tools.install_sandbox.models import EffectKind, Scope
from tools.install_sandbox.specs import (
    EXPECTED_TARGETS,
    SpecError,
    load_catalog,
    load_target,
)


SPEC_DIR = Path("tools/install_sandbox/specs")


def test_current_catalog_strictly_loads_all_24_targets_and_47_pairs():
    catalog = load_catalog(SPEC_DIR)

    assert tuple(catalog) == EXPECTED_TARGETS
    assert len(catalog) == 24
    assert sum(
        target.supports(scope) for target in catalog.values() for scope in Scope
    ) == 47
    assert catalog["cursor"].unsupported == {
        Scope.USER: (
            "Cursor installs only a project-local .cursor rule in the current "
            "working directory."
        )
    }
    assert catalog["hermes"].limitations == (
        "Normal Linux Hermes behavior is validated; Windows %LOCALAPPDATA% "
        "installation is not verified.",
    )
    windows_limitation = (
        "Linux Docker verifies packaged Windows payload consistency only; "
        "Windows paths, permissions, shells, cleanup, and runtime discovery "
        "are not verified."
    )
    assert catalog["windows"].limitations == (windows_limitation,)
    assert catalog["antigravity-windows"].limitations == (
        windows_limitation.replace(
            "packaged Windows payload",
            "packaged Antigravity-Windows payload",
        ),
    )


def test_catalog_payloads_and_reference_bundles_resolve_in_current_source():
    catalog = load_catalog(SPEC_DIR)

    for target in catalog.values():
        for scope in target.scopes.values():
            for effect in scope.effects:
                if effect.source:
                    assert Path(effect.source).is_file(), (
                        target.name,
                        effect.source,
                    )
                if effect.kind is EffectKind.SKILL and effect.reference_bundle:
                    names = {
                        item.name
                        for item in (
                            Path("graphify/skills")
                            / effect.reference_bundle
                            / "references"
                        ).iterdir()
                        if item.is_file()
                    }
                    assert len(names) == 8


def test_current_command_exceptions_match_real_direct_cli_surfaces():
    catalog = load_catalog(SPEC_DIR)
    direct_user_uninstall = {
        name
        for name, target in catalog.items()
        if target.supports(Scope.USER)
        and target.scopes[Scope.USER].uninstall is not None
    }

    assert direct_user_uninstall == {
        "agents",
        "amp",
        "antigravity",
        "claude",
        "copilot",
        "devin",
        "gemini",
        "kilo",
        "pi",
        "vscode",
    }
    assert {
        name
        for name, target in catalog.items()
        if target.supports(Scope.PROJECT)
        and target.scopes[Scope.PROJECT].install is not None
    } == {"cursor", "kilo", "kiro", "vscode"}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "mystery: true\nscopes:\n  user:\n    effects: []\n",
            "unknown keys",
        ),
        (
            "unsupported:\n  project: no\nscopes:\n  user:\n    effects:\n"
            "      - {root: nowhere, path: ok}\n",
            "invalid",
        ),
        (
            "unsupported:\n  project: no\nscopes:\n  user:\n    effects:\n"
            "      - {root: home, path: ../escape}\n",
            "safe relative",
        ),
        (
            "unsupported:\n  project: no\nscopes:\n  user:\n    effects:\n"
            "      - {kind: section, root: home, path: notes.md, "
            "marker: '## graphify'}\n",
            "require source or required_text",
        ),
    ],
)
def test_loader_rejects_unknown_keys_bad_roots_and_unsafe_paths(
    tmp_path, body, message
):
    spec = tmp_path / "sample.yaml"
    spec.write_text(body, encoding="utf-8")

    with pytest.raises(SpecError, match=message):
        load_target(spec)


def test_catalog_rejects_missing_targets(tmp_path):
    (tmp_path / "agents.yaml").write_text(
        "unsupported:\n  project: unavailable\n"
        "scopes:\n  user:\n    effects:\n"
        "      - {root: home, path: x}\n",
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="target catalog mismatch"):
        load_catalog(tmp_path)
