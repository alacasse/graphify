import shutil
from pathlib import Path

from tools.install_sandbox.effects import REFERENCE_NAMES, resolve_effect
from tools.install_sandbox.lifecycle import (
    install_command,
    run_scenario,
    scenario_steps,
    uninstall_command,
)
from tools.install_sandbox.models import (
    CommandResult,
    Effect,
    EffectKind,
    Root,
    SandboxRoots,
    Scenario,
    Scope,
    ScopeSpec,
    TargetSpec,
)


def make_roots(tmp_path):
    values = {
        name: tmp_path / name
        for name in (
            "home",
            "xdg",
            "project",
            "user_cwd",
            "source",
            "repo_mount",
            "output",
        )
    }
    for path in values.values():
        path.mkdir()
    return SandboxRoots(**values)


def progressive_scenario():
    effect = Effect(
        kind=EffectKind.SKILL,
        root=Root.PROJECT,
        path=".demo/skills/graphify/SKILL.md",
        source="graphify/skill.md",
        reference_bundle="demo",
    )
    target = TargetSpec(
        name="demo",
        scopes={Scope.PROJECT: ScopeSpec(effects=(effect,))},
        unsupported={Scope.USER: "test-only"},
    )
    return Scenario(target=target, scope=Scope.PROJECT)


def test_commands_and_lifecycle_order_derive_common_project_policy():
    scenario = progressive_scenario()

    assert install_command(scenario) == (
        "graphify",
        "install",
        "--project",
        "--platform",
        "demo",
    )
    assert uninstall_command(scenario) == (
        "graphify",
        "uninstall",
        "--project",
        "--platform",
        "demo",
    )
    assert scenario_steps(scenario) == (
        "install",
        "reinstall",
        "repair-progressive-sidecars",
        "uninstall",
    )


def test_full_lifecycle_is_idempotent_repairs_sidecars_and_preserves_user_content(
    tmp_path,
):
    roots = make_roots(tmp_path)
    scenario = progressive_scenario()
    skill_source = roots.source / "graphify/skill.md"
    refs_source = roots.source / "graphify/skills/demo/references"
    refs_source.mkdir(parents=True)
    skill_source.parent.mkdir(parents=True, exist_ok=True)
    skill_source.write_text(
        "\n".join(f"(references/{name})" for name in REFERENCE_NAMES),
        encoding="utf-8",
    )
    for name in REFERENCE_NAMES:
        (refs_source / name).write_text(name, encoding="utf-8")

    def fake_executor(argv, cwd, env, artifact_dir, label):
        effect = scenario.contract.effects[0]
        skill = resolve_effect(effect, roots.effect_roots())
        if "uninstall" in argv:
            skill.unlink(missing_ok=True)
            (skill.parent / ".graphify_version").unlink(missing_ok=True)
            shutil.rmtree(skill.parent / "references", ignore_errors=True)
            shutil.rmtree(skill.parent / "references.tmp", ignore_errors=True)
        else:
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_bytes(skill_source.read_bytes())
            (skill.parent / ".graphify_version").write_text(
                "1.0", encoding="utf-8"
            )
            shutil.rmtree(skill.parent / "references", ignore_errors=True)
            shutil.rmtree(skill.parent / "references.tmp", ignore_errors=True)
            shutil.copytree(refs_source, skill.parent / "references")
        return CommandResult(tuple(argv), str(cwd), 0, "", "")

    result = run_scenario(scenario, roots, executor=fake_executor)

    assert result.status == "PASS"
    assert [phase.name for phase in result.phases] == [
        "install",
        "reinstall",
        "repair-progressive-sidecars",
        "uninstall",
    ]
    assert all(
        check.passed for phase in result.phases for check in phase.validations
    )
    assert (roots.project / "user-owned.txt").read_text(encoding="utf-8")
    assert not (
        roots.project / ".demo/skills/graphify/references.tmp"
    ).exists()
    assert (roots.output / "scenarios/demo-project/result.json").is_file()


def test_lifecycle_reports_not_applicable_user_uninstall(tmp_path):
    roots = make_roots(tmp_path)
    source = roots.source / "owned.txt"
    source.write_text("owned", encoding="utf-8")
    effect = Effect(
        kind=EffectKind.FILE,
        root=Root.HOME,
        path="owned.txt",
        source="owned.txt",
    )
    target = TargetSpec(
        name="demo",
        scopes={Scope.USER: ScopeSpec(effects=(effect,))},
        unsupported={Scope.PROJECT: "test-only"},
    )
    scenario = Scenario(target=target, scope=Scope.USER)

    def fake_executor(argv, cwd, env, artifact_dir, label):
        (roots.home / "owned.txt").write_text("owned", encoding="utf-8")
        return CommandResult(tuple(argv), str(cwd), 0, "", "")

    result = run_scenario(scenario, roots, executor=fake_executor)

    assert result.status == "PASS"
    assert result.phases[-1].status == "NOT_APPLICABLE"
    assert (roots.home / "user-owned.txt").is_file()

