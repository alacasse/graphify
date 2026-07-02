from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.effects import file_effect_generated_artifacts
from tools.install_sandbox.effects import file_effect_oracle
from tools.install_sandbox.effects import scenario_file_effects_adapter
from tools.install_sandbox.targets.reference_resolution import PackagedReferenceResolution
from tools.install_sandbox.targets.install_target_models import ExpectedPath, InstallSurface, Scenario

# ScenarioFileEffectsAdapter coverage lives here. Lifecycle sequencing and
# protocol shape remain in test_scenario_lifecycle.py.


@pytest.fixture
def roots(tmp_path) -> dict[str, Path]:
    paths = {"home": tmp_path / "home", "project": tmp_path / "project", "user_cwd": tmp_path / "user-cwd"}
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


@pytest.fixture
def oracle(roots) -> file_effect_oracle.FileEffectOracle:
    def packaged_reference_resolution(platform: str) -> PackagedReferenceResolution:
        if platform == "claude":
            return resolution("available", ("query.md", "update.md"), "claude refs")
        if platform == "empty":
            return resolution("empty", detail="empty refs")
        if platform == "no_eligible":
            return resolution("no_eligible_bundle", detail="no eligible refs")
        if platform == "missing":
            return resolution("missing", detail="missing /package/refs")
        if platform == "not_directory":
            return resolution("not_directory", detail="not_directory /package/refs")
        return resolution("intentionally_absent", detail="absent refs")

    return file_effect_oracle.FileEffectOracle(
        roots=roots,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=lambda: "9.9.9",
        manifest_prune_dirs=set(file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES),
    )


def scenario(platform: str, *expected: InstallSurface, scope: str = "project") -> Scenario:
    return Scenario(
        target_name=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
    )


class RecordingScenarioFileEffectsOracle:
    def __init__(self, roots: dict[str, Path]) -> None:
        self.roots = roots
        self.calls: list[tuple[object, ...]] = []
        self.expected_graphify_version = lambda: "9.9.9"

    def packaged_reference_resolution(self, platform: str) -> PackagedReferenceResolution:
        return resolution("intentionally_absent", detail="absent refs")

    def seed_user_owned_content(self, scenario_arg: Scenario) -> None:
        self.calls.append(("seed_user_owned_content", scenario_arg.target_name))

    def scenario_file_state(self, scenario_arg: Scenario) -> dict[str, dict[str, object]]:
        self.calls.append(("scenario_file_state", scenario_arg.target_name))
        return {"state": {"exists": True}}

    def pruned_file_walk(self, base: Path):
        yield from file_effect_generated_artifacts.pruned_file_walk(base, set())

    def generated_file_decision(
        self,
        scenario_arg: Scenario,
        root_name: str,
        relative: Path,
        path: Path,
        *,
        apply_excludes: bool,
        expected_keys: set[tuple[str, str]] | None = None,
    ):
        return file_effect_generated_artifacts.generated_file_decision(
            scenario_arg,
            root_name,
            relative,
            path,
            apply_excludes=apply_excludes,
            expected_keys=expected_keys,
        )

    def copy_generated_files(self, scenario_arg: Scenario, artifact_dir: Path) -> None:
        self.calls.append(("copy_generated_files", scenario_arg.target_name, artifact_dir))

    def seed_stale_skill_sidecars(self, scenario_arg: Scenario) -> list[dict[str, object]]:
        self.calls.append(("seed_stale_skill_sidecars", scenario_arg.target_name))
        return [{"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}]


def test_scenario_file_effects_adapter_preserves_repeat_install_and_universal_uninstall_shapes(oracle, roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter(oracle, write_manifest, equivalence_check)
    repeat_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    before = {
        "project/AGENTS.md": {"exists": True, "sha256": "a"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/AGENTS.md": {"exists": True, "sha256": "b"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }

    repeat_checks = adapter.repeat_install_checks(repeat_scenario, before, after, phase="repeat_install")

    assert repeat_checks == [
        {"path": "project/AGENTS.md", "ok": False, "detail": "changed_after_repeat_install"},
        {"path": "project/notes.md", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"},
    ]

    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", ".second/graphify/SKILL.md"))
    (roots["project"] / "first.md").write_text("still installed\n", encoding="utf-8")
    expected_generated = roots["home"] / ".second/graphify/SKILL.md"
    expected_generated.parent.mkdir(parents=True)
    expected_generated.write_text("expected generated path may remain\n", encoding="utf-8")
    unexpected_generated = roots["project"] / "leftover/graphify.md"
    unexpected_generated.parent.mkdir(parents=True)
    unexpected_generated.write_text("generated by graphify\n", encoding="utf-8")
    install_checks = [{"path": "install", "ok": True, "detail": "installed"}]

    universal_checks = adapter.universal_uninstall_checks(repeat_scenario, (first, second), install_checks)

    assert universal_checks == [
        {"path": "install", "ok": True, "detail": "installed"},
        {
            "path": str(roots["project"] / "first.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "project",
            "relative": "first.md",
        },
        {
            "path": str(roots["home"] / ".second/graphify/SKILL.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "home",
            "relative": ".second/graphify/SKILL.md",
        },
        {
            "path": str(unexpected_generated),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_universal_uninstall",
            "root": "project",
            "relative": "leftover/graphify.md",
        },
    ]


def test_scenario_file_effects_adapter_orders_universal_uninstall_check_groups(oracle, roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter(oracle, write_manifest, equivalence_check)
    runner = scenario("runner", ExpectedPath("project", "runner.md"))
    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", "second.md"))
    first_path = roots["project"] / "first.md"
    first_path.write_text("still installed\n", encoding="utf-8")
    second_path = roots["home"] / "second.md"
    second_path.write_text("still installed\n", encoding="utf-8")
    leftover = roots["project"] / "leftover/graphify.md"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("generated by graphify\n", encoding="utf-8")
    install_checks = [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
    ]

    assert adapter.universal_uninstall_checks(runner, (first, second), install_checks) == [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
        {"path": str(first_path), "ok": False, "detail": "still_exists", "root": "project", "relative": "first.md"},
        {"path": str(second_path), "ok": False, "detail": "still_exists", "root": "home", "relative": "second.md"},
        {
            "path": str(leftover),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_universal_uninstall",
            "root": "project",
            "relative": "leftover/graphify.md",
        },
    ]


def test_scenario_file_effects_adapter_preserves_phase_result_shapes(roots, tmp_path) -> None:
    calls: list[tuple[object, ...]] = []

    def write_manifest(path, roots_arg, **kwargs) -> None:
        calls.append(("write_manifest", path, roots_arg, kwargs))

    def equivalence_check(scenario_arg, env, artifact_dir):
        calls.append(("equivalence_check", scenario_arg.target_name, env, artifact_dir))
        return [{"path": "equivalence", "ok": True, "detail": "equivalent"}]

    recording_oracle = RecordingScenarioFileEffectsOracle(roots)
    recording_oracle.calls = calls
    adapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    adapter_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    artifact_dir = tmp_path / "artifact"
    manifest_path = tmp_path / "manifest.json"
    expected_path = roots["project"] / "AGENTS.md"
    expected_path.write_text("installed\n", encoding="utf-8")

    assert adapter.seed_scenario_inputs(adapter_scenario) is None
    adapter.write_manifest(manifest_path, roots, scenario=adapter_scenario)

    initial = adapter.initial_install_effects(adapter_scenario, artifact_dir, phase="install")
    assert initial.state_after_install == {"state": {"exists": True}}
    assert initial.install_checks == [
        {"path": str(expected_path), "ok": True, "detail": "file", "root": "project", "relative": "AGENTS.md"},
        {"path": str(expected_path), "ok": True, "detail": "allowed_root"},
    ]
    assert initial.scope_checks == []
    assert initial.unexpected_install_checks == [
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_install"}
    ]
    assert adapter.archive_initial_install_artifacts(adapter_scenario, artifact_dir) is None

    repeat = adapter.repeat_install_effects(
        adapter_scenario,
        {"state": {"exists": True}},
        phase="repeat_install",
    )
    assert repeat.state_after_repeat == {"state": {"exists": True}}
    assert repeat.idempotency_checks == [
        {"path": "state", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"},
    ]
    assert adapter.seed_stale_sidecar_repair(adapter_scenario) == [
        {"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    stale_repair = adapter.stale_sidecar_repair_effects(adapter_scenario, phase="stale_sidecar_repair")
    assert stale_repair.stale_sidecar_repair_checks == [
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_stale_sidecar_repair"},
    ]

    expected_path.unlink()
    uninstall = adapter.uninstall_effects(adapter_scenario, phase="uninstall")
    assert uninstall.uninstall_checks == [
        {"path": str(expected_path), "ok": True, "detail": "removed", "root": "project", "relative": "AGENTS.md"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_uninstall"},
    ]
    assert uninstall.unexpected_uninstall_checks == []
    assert adapter.equivalence_checks(adapter_scenario, {"HOME": str(roots["home"])}, artifact_dir) == [
        {"path": "equivalence", "ok": True, "detail": "equivalent"}
    ]
    assert adapter.universal_install_effects(adapter_scenario) == [
        {"path": str(expected_path), "ok": False, "detail": "missing", "root": "project", "relative": "AGENTS.md"},
        {"path": str(expected_path), "ok": True, "detail": "allowed_root"},
    ]
    assert adapter.universal_uninstall_checks(
        adapter_scenario,
        (scenario("first", ExpectedPath("project", "first.md")), scenario("second", ExpectedPath("home", "second.md"))),
        [{"path": "install", "ok": True, "detail": "installed"}],
    ) == [
        {"path": "install", "ok": True, "detail": "installed"},
        {
            "path": str(roots["project"] / "first.md"),
            "ok": True,
            "detail": "removed",
            "root": "project",
            "relative": "first.md",
        },
        {
            "path": str(roots["home"] / "second.md"),
            "ok": True,
            "detail": "removed",
            "root": "home",
            "relative": "second.md",
        },
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_universal_uninstall"},
    ]
    assert adapter.disposable_artifact_checks(roots["project"] / "graphify-out", removed=True) == [
        {"path": str(roots["project"] / "graphify-out"), "ok": True, "detail": "removed"}
    ]

    assert calls == [
        ("seed_user_owned_content", "unit"),
        ("write_manifest", manifest_path, roots, {"scenario": adapter_scenario}),
        ("scenario_file_state", "unit"),
        ("copy_generated_files", "unit", artifact_dir),
        ("scenario_file_state", "unit"),
        ("seed_stale_skill_sidecars", "unit"),
        ("equivalence_check", "unit", {"HOME": str(roots["home"])}, artifact_dir),
    ]


def test_scenario_file_effects_adapter_preserves_setup_method_shapes(roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    recording_oracle = RecordingScenarioFileEffectsOracle(roots)
    adapter = scenario_file_effects_adapter.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    setup_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    assert adapter.seed_scenario_inputs(setup_scenario) is None
    assert adapter.seed_stale_sidecar_repair(setup_scenario) == [
        {"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    assert recording_oracle.calls == [
        ("seed_user_owned_content", "unit"),
        ("seed_stale_skill_sidecars", "unit"),
    ]
