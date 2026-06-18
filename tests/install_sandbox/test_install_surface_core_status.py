from __future__ import annotations

from pathlib import Path

from tools.install_sandbox import install_surface_core
from tools.install_sandbox import platform_specs
from tools.install_sandbox.platform_specs import InstallSurface

# Status-decision ownership lives here. Sidecar, state-plan, and generated-file
# Installer Core decisions live in the sibling test_install_surface_core_* modules.


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
