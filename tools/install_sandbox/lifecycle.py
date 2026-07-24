"""In-container installer lifecycle execution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .effects import (
    resolve_effect,
    snapshot,
    snapshot_digest,
    validate_installed,
    validate_removed,
)
from .models import (
    CommandResult,
    EffectKind,
    PhaseResult,
    Root,
    SandboxRoots,
    Scenario,
    ScenarioResult,
    Scope,
    ValidationResult,
)


COMMAND_TIMEOUT_SECONDS = 180
PACKAGE_TIMEOUT_SECONDS = 900
USER_SENTINEL = "graphify sandbox unrelated user content\n"


@dataclass(frozen=True)
class Seed:
    path: Path
    kind: str


CommandExecutor = Callable[
    [tuple[str, ...], Path, Mapping[str, str], Path, str], CommandResult
]


def scenario_steps(scenario: Scenario) -> tuple[str, ...]:
    steps = ["install", "reinstall"]
    if any(
        effect.kind is EffectKind.SKILL and effect.reference_bundle
        for effect in scenario.contract.effects
    ):
        steps.append("repair-progressive-sidecars")
    steps.append("uninstall" if uninstall_command(scenario) else "uninstall-not-applicable")
    return tuple(steps)


def install_command(scenario: Scenario) -> tuple[str, ...]:
    if scenario.contract.install:
        return scenario.contract.install
    command = ["graphify", "install"]
    if scenario.scope is Scope.PROJECT:
        command.append("--project")
    command.extend(["--platform", scenario.target.name])
    return tuple(command)


def uninstall_command(scenario: Scenario) -> tuple[str, ...] | None:
    if scenario.contract.uninstall:
        return scenario.contract.uninstall
    if scenario.scope is Scope.PROJECT:
        return (
            "graphify",
            "uninstall",
            "--project",
            "--platform",
            scenario.target.name,
        )
    return None


def command_environment(roots: SandboxRoots) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(roots.home)
    env["XDG_CONFIG_HOME"] = str(roots.xdg)
    env["PATH"] = f"{roots.home / '.local' / 'bin'}:{env.get('PATH', '')}"
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("LOCALAPPDATA", None)
    return env


def execute_command(
    argv: tuple[str, ...],
    cwd: Path,
    env: Mapping[str, str],
    artifact_dir: Path,
    label: str,
) -> CommandResult:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timed_out = False
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            shell=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    (artifact_dir / f"{label}.stdout.log").write_text(stdout, encoding="utf-8")
    (artifact_dir / f"{label}.stderr.log").write_text(stderr, encoding="utf-8")
    record = {
        "label": label,
        "argv": list(argv),
        "cwd": str(cwd),
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    with (artifact_dir / "commands.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return CommandResult(
        argv=argv,
        cwd=str(cwd),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


def reset_scenario_roots(roots: SandboxRoots) -> None:
    for base, preserve in (
        (roots.home, {".local"}),
        (roots.xdg, set()),
        (roots.project, set()),
        (roots.user_cwd, set()),
    ):
        base.mkdir(parents=True, exist_ok=True)
        for child in base.iterdir():
            if child.name in preserve:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()


def seed_user_content(scenario: Scenario, roots: Mapping[Root, Path]) -> list[Seed]:
    seeds: list[Seed] = []
    for root, base in roots.items():
        base.mkdir(parents=True, exist_ok=True)
        sentinel = base / "user-owned.txt"
        sentinel.write_text(USER_SENTINEL, encoding="utf-8")
        seeds.append(Seed(sentinel, "sentinel"))

    for effect in scenario.contract.effects:
        path = resolve_effect(effect, roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        sibling = path.parent / "unrelated.txt"
        if not sibling.exists():
            sibling.write_text(USER_SENTINEL, encoding="utf-8")
            seeds.append(Seed(sibling, "sentinel"))
        if effect.kind is EffectKind.SECTION and not path.exists():
            path.write_text("# User notes\n\nkeep this section\n", encoding="utf-8")
            seeds.append(Seed(path, "section"))
        elif effect.kind is EffectKind.JSON and not path.exists():
            path.write_text(
                json.dumps({"user_owned": {"keep": True}}, indent=2) + "\n",
                encoding="utf-8",
            )
            seeds.append(Seed(path, "json"))
    return seeds


def validate_user_content(seeds: Iterable[Seed]) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for seed in seeds:
        passed = seed.path.is_file()
        detail = f"{seed.path} still exists"
        if passed and seed.kind == "sentinel":
            passed = seed.path.read_text(encoding="utf-8") == USER_SENTINEL
            detail = f"{seed.path} retains unrelated content"
        elif passed and seed.kind == "section":
            passed = "keep this section" in seed.path.read_text(encoding="utf-8")
            detail = f"{seed.path} retains the user's Markdown section"
        elif passed and seed.kind == "json":
            try:
                value = json.loads(seed.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                value = {}
            passed = value.get("user_owned") == {"keep": True}
            detail = f"{seed.path} retains the user's JSON entry"
        results.append(
            ValidationResult(
                check="unrelated user content",
                passed=passed,
                detail=detail,
            )
        )
    return results


def seed_stale_sidecars(
    scenario: Scenario,
    roots: Mapping[Root, Path],
) -> int:
    seeded = 0
    for effect in scenario.contract.effects:
        if effect.kind is not EffectKind.SKILL or not effect.reference_bundle:
            continue
        skill = resolve_effect(effect, roots)
        references = skill.parent / "references"
        references.mkdir(parents=True, exist_ok=True)
        (references / "update.md").write_text("stale\n", encoding="utf-8")
        (references / "stale.md").write_text("stale\n", encoding="utf-8")
        staged = skill.parent / "references.tmp"
        staged.mkdir(parents=True, exist_ok=True)
        (staged / "stale.md").write_text("stale\n", encoding="utf-8")
        seeded += 1
    return seeded


def _phase_status(
    command: CommandResult | None,
    validations: Iterable[ValidationResult],
) -> str:
    if command is not None and not command.passed:
        return "FAIL"
    return "PASS" if all(item.passed for item in validations) else "FAIL"


def _write_snapshot(
    path: Path,
    roots: Mapping[Root, Path],
) -> dict[str, list[dict[str, object]]]:
    value = snapshot(roots)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def run_scenario(
    scenario: Scenario,
    roots: SandboxRoots,
    *,
    executor: CommandExecutor = execute_command,
) -> ScenarioResult:
    artifact_dir = roots.output / "scenarios" / scenario.name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    reset_scenario_roots(roots)
    effect_roots = roots.effect_roots()
    seeds = seed_user_content(scenario, effect_roots)
    _write_snapshot(artifact_dir / "before.json", effect_roots)
    env = command_environment(roots)
    cwd = roots.user_cwd if scenario.scope is Scope.USER else roots.project
    phases: list[PhaseResult] = []

    install = executor(
        install_command(scenario), cwd, env, artifact_dir, "install"
    )
    installed_checks = validate_installed(
        scenario.contract.effects, effect_roots, roots.source
    )
    installed_checks.extend(validate_user_content(seeds))
    installed_snapshot = _write_snapshot(
        artifact_dir / "after-install.json", effect_roots
    )
    phases.append(
        PhaseResult(
            name="install",
            status=_phase_status(install, installed_checks),
            command=install,
            validations=installed_checks,
        )
    )

    reinstall = executor(
        install_command(scenario), cwd, env, artifact_dir, "reinstall"
    )
    reinstall_checks = validate_installed(
        scenario.contract.effects, effect_roots, roots.source
    )
    reinstall_checks.extend(validate_user_content(seeds))
    reinstalled_snapshot = _write_snapshot(
        artifact_dir / "after-reinstall.json", effect_roots
    )
    reinstall_checks.append(
        ValidationResult(
            check="idempotent filesystem state",
            passed=snapshot_digest(installed_snapshot)
            == snapshot_digest(reinstalled_snapshot),
            detail="second install leaves the same filesystem snapshot",
        )
    )
    phases.append(
        PhaseResult(
            name="reinstall",
            status=_phase_status(reinstall, reinstall_checks),
            command=reinstall,
            validations=reinstall_checks,
        )
    )

    sidecar_count = seed_stale_sidecars(scenario, effect_roots)
    if sidecar_count:
        repair = executor(
            install_command(scenario), cwd, env, artifact_dir, "repair-sidecars"
        )
        repair_checks = validate_installed(
            scenario.contract.effects, effect_roots, roots.source
        )
        repair_checks.extend(validate_user_content(seeds))
        repaired_snapshot = _write_snapshot(
            artifact_dir / "after-repair.json", effect_roots
        )
        repair_checks.append(
            ValidationResult(
                check="repaired stable filesystem state",
                passed=snapshot_digest(installed_snapshot)
                == snapshot_digest(repaired_snapshot),
                detail="repair removes stale references and restores installed state",
            )
        )
        phases.append(
            PhaseResult(
                name="repair-progressive-sidecars",
                status=_phase_status(repair, repair_checks),
                command=repair,
                validations=repair_checks,
            )
        )

    uninstall_argv = uninstall_command(scenario)
    if uninstall_argv is None:
        preserve_checks = validate_user_content(seeds)
        phases.append(
            PhaseResult(
                name="uninstall",
                status="NOT_APPLICABLE",
                validations=preserve_checks,
            )
        )
        _write_snapshot(artifact_dir / "after-uninstall-not-applicable.json", effect_roots)
    else:
        uninstall = executor(
            uninstall_argv, cwd, env, artifact_dir, "uninstall"
        )
        uninstall_checks = validate_removed(
            scenario.contract.effects,
            effect_roots,
            roots.source,
        )
        uninstall_checks.extend(validate_user_content(seeds))
        _write_snapshot(artifact_dir / "after-uninstall.json", effect_roots)
        phases.append(
            PhaseResult(
                name="uninstall",
                status=_phase_status(uninstall, uninstall_checks),
                command=uninstall,
                validations=uninstall_checks,
            )
        )

    status = "PASS" if all(
        phase.status in {"PASS", "NOT_APPLICABLE"} for phase in phases
    ) else "FAIL"
    result = ScenarioResult(
        scenario=scenario.name,
        target=scenario.target.name,
        scope=scenario.scope.value,
        status=status,
        phases=phases,
        limitations=scenario.target.limitations,
        artifact_dir=str(artifact_dir.relative_to(roots.output)),
    )
    (artifact_dir / "result.json").write_text(
        json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def copy_and_install_package(roots: SandboxRoots) -> dict[str, object]:
    if roots.source.exists():
        shutil.rmtree(roots.source)
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        "__pycache__",
        "graphify-out",
        "out",
        "*.pyc",
    )
    shutil.copytree(roots.repo_mount, roots.source, ignore=ignored)
    env = command_environment(roots)
    package_dir = roots.output / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    argv = (sys.executable, "-m", "pip", "install", "--user", str(roots.source))
    result = execute_command(argv, Path("/tmp"), env, package_dir, "pip-install")
    if not result.passed:
        raise RuntimeError("package installation failed; see package logs")
    probe = execute_command(
        ("graphify", "--version"),
        Path("/tmp"),
        env,
        package_dir,
        "version",
    )
    if not probe.passed:
        raise RuntimeError("installed graphify version probe failed")
    return {
        "install_argv": list(argv),
        "source": str(roots.source),
        "repo_mount": str(roots.repo_mount),
        "repo_mount_read_only": probe_read_only(roots.repo_mount),
        "version": probe.stdout.strip(),
    }


def probe_read_only(path: Path) -> bool:
    probe = path / ".graphify-install-sandbox-write-probe"
    try:
        probe.write_text("unsafe", encoding="utf-8")
    except OSError:
        return True
    probe.unlink(missing_ok=True)
    return False


def run_purge_check(
    roots: SandboxRoots,
    *,
    executor: CommandExecutor = execute_command,
) -> dict[str, object]:
    reset_scenario_roots(roots)
    graph = roots.project / "graphify-out" / "graph.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text("{}\n", encoding="utf-8")
    sentinel = roots.project / "user-owned.txt"
    sentinel.write_text(USER_SENTINEL, encoding="utf-8")
    artifact_dir = roots.output / "purge"
    command = executor(
        ("graphify", "uninstall", "--purge"),
        roots.project,
        command_environment(roots),
        artifact_dir,
        "purge",
    )
    passed = (
        command.passed
        and not graph.parent.exists()
        and sentinel.read_text(encoding="utf-8") == USER_SENTINEL
    )
    result = {
        "status": "PASS" if passed else "FAIL",
        "command": command.as_dict(),
        "graphify_out_removed": not graph.parent.exists(),
        "unrelated_content_preserved": sentinel.is_file()
        and sentinel.read_text(encoding="utf-8") == USER_SENTINEL,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
