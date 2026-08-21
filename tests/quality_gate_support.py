"""Shared black-box fixture support for install-sandbox quality-gate tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts.install_sandbox_quality_policy import PYTHON_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCRIPT = PROJECT_ROOT / "scripts" / "install_sandbox_quality.py"
RUFF_CONFIG = PROJECT_ROOT / "ruff.install-sandbox.toml"
PYRIGHT_CONFIG = PROJECT_ROOT / "pyrightconfig.install-sandbox.json"
LOCKFILE = PROJECT_ROOT / "uv.lock"
FROZEN_PYTHON_RUN = ("uv", "run", "--frozen", "--python", PYTHON_VERSION)
APPROVED_TEMPORARY_COVERAGE_EXCLUSIONS = (
    "tools/install_sandbox/ci_result.py",
    "tools/install_sandbox/docker.py",
    "tools/install_sandbox/effects.py",
    "tools/install_sandbox/lifecycle.py",
    "tools/install_sandbox/models.py",
    "tools/install_sandbox/reporting.py",
    "tools/install_sandbox/run.py",
    "tools/install_sandbox/run_artifacts.py",
    "tools/install_sandbox/sandbox_runner.py",
    "tools/install_sandbox/specs.py",
)


def run_quality_gate(
    repository: Path,
    *,
    arguments: tuple[str, ...] = ("fast",),
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    child_environment = os.environ.copy()
    child_environment["UV_PROJECT"] = str(PROJECT_ROOT)
    if environment is not None:
        child_environment.update(environment)
    child_environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(repository), child_environment.get("PYTHONPATH")) if value
    )
    return subprocess.run(
        [
            *FROZEN_PYTHON_RUN,
            "python",
            str(QUALITY_SCRIPT),
            *arguments,
        ],
        cwd=repository,
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
    )


def copy_docker_gate_fixture(tmp_path: Path) -> Path:
    """Create temporary adapters for the supported Docker and classifier seams."""

    fixture_root = tmp_path / "repository"
    production = fixture_root / "tools" / "install_sandbox"
    production.mkdir(parents=True)
    (fixture_root / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (production / "__init__.py").write_text("", encoding="utf-8")
    (fixture_root / "pyproject.toml").write_text(
        '[project]\nname = "docker-gate-fixture"\nversion = "0"\n',
        encoding="utf-8",
    )
    (fixture_root / "graphify").mkdir()
    specs = production / "specs"
    specs.mkdir()
    (specs / "fixture.yaml").write_text(
        """scopes:
  user:
    effects:
      - root: home
        path: .fixture
  project:
    effects:
      - root: project
        path: .fixture
""",
        encoding="utf-8",
    )
    (production / "run.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import argparse
            import json
            import os
            from pathlib import Path


            parser = argparse.ArgumentParser()
            parser.add_argument("--repo", required=True)
            selection = parser.add_mutually_exclusive_group(required=True)
            selection.add_argument("--target", choices=("fixture",))
            selection.add_argument("--all", action="store_true", dest="all_targets")
            parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
            parser.add_argument("--output", required=True, type=Path)
            args = parser.parse_args()

            configuration = json.loads(os.environ.get("QUALITY_DOCKER_FIXTURE", "{}"))
            runner_exit = int(configuration.get("runner_exit", 0))
            recorded_exit = int(configuration.get("recorded_exit", runner_exit))
            state = configuration.get("state", "passed")
            selected = {
                "target": args.target,
                "all": args.all_targets,
                "scope": args.scope,
            }
            args.output.mkdir(parents=True, exist_ok=True)
            print(
                "runner raw: "
                f"target={args.target} all={args.all_targets} scope={args.scope} exit={runner_exit}"
            )

            if configuration.get("run_mode", "valid") != "missing":
                run = {
                    "schema_version": 1,
                    "run_id": "fixture-run",
                    "managed": False,
                    "started_at": "2026-08-18T00:00:00Z",
                    "updated_at": "2026-08-18T00:01:00Z",
                    "finished_at": "2026-08-18T00:01:00Z",
                    "repository": str(Path(args.repo).resolve()),
                    "output": str(args.output.resolve()),
                    "selection": selected,
                    "phase": "container_run",
                    "state": state,
                    "exit_code": recorded_exit,
                }
                if configuration.get("run_mode") == "malformed":
                    (args.output / "run.json").write_text("{", encoding="utf-8")
                else:
                    if configuration.get("run_mode") == "incomplete":
                        run.pop("phase")
                    (args.output / "run.json").write_text(json.dumps(run), encoding="utf-8")

            manifest_mode = configuration.get("manifest_mode", "valid")
            if manifest_mode != "missing":
                manifest_selection = dict(selected)
                if manifest_mode == "mismatch":
                    manifest_selection["scope"] = "user"
                if manifest_mode == "incomplete":
                    manifest = {
                        "harness": "graphify-install-sandbox-v8",
                        "selection": manifest_selection,
                    }
                else:
                    scenario_status = "FAIL" if manifest_mode == "finding" else "PASS"
                    phase_status = scenario_status
                    identities = [
                        ("fixture-user", "fixture", "user"),
                        ("fixture-project", "fixture", "project"),
                    ]
                    if args.all_targets:
                        identities.extend(
                            [
                                ("universal-uninstall-user", "multiple", "user"),
                                ("universal-uninstall-project", "multiple", "project"),
                            ]
                        )
                    scenarios = []
                    for scenario_name, target, scope in identities:
                        scenario = {
                            "scenario": scenario_name,
                            "target": target,
                            "scope": scope,
                            "status": scenario_status,
                            "limitations": [],
                            "artifact_dir": f"scenarios/{scenario_name}",
                            "phases": [
                                {
                                    "name": "install",
                                    "status": phase_status,
                                    "command": {
                                        "argv": ["graphify", "install", "fixture"],
                                        "cwd": "/tmp/project",
                                        "exit_code": 0,
                                        "timed_out": False,
                                    },
                                    "validations": [],
                                }
                            ],
                        }
                        scenarios.append(scenario)
                    if manifest_mode == "partial_coverage":
                        scenarios.pop()
                    if manifest_mode == "bad_phase_command":
                        scenarios[0]["phases"][0]["command"]["exit_code"] = 1
                    if manifest_mode == "na_command":
                        scenarios[0]["phases"][0]["status"] = "NOT_APPLICABLE"
                    if manifest_mode == "unsupported_scope":
                        scenarios[0].update(
                            {
                                "status": "UNSUPPORTED",
                                "artifact_dir": None,
                                "phases": [],
                            }
                        )
                    purge = {
                        "status": "PASS",
                        "command": {
                            "argv": ["graphify", "uninstall", "--purge"],
                            "cwd": "/tmp/project",
                            "exit_code": 0,
                            "timed_out": False,
                        },
                        "graphify_out_removed": True,
                        "unrelated_content_preserved": True,
                    }
                    if manifest_mode == "bad_purge_command":
                        purge["command"]["timed_out"] = True
                    summary = {scenario_status: len(scenarios)}
                    if manifest_mode == "unsupported_scope":
                        summary = {"PASS": len(scenarios) - 1, "UNSUPPORTED": 1}
                    manifest = {
                        "harness": "graphify-install-sandbox-v8",
                        "generated_at": "2026-08-18T00:00:00+00:00",
                        "repo": "/tmp/repo",
                        "selection": manifest_selection,
                        "package": {
                            "package_version": "0",
                            "public_install_targets": ["fixture"],
                        },
                        "summary": summary,
                        "scenario_count": len(scenarios),
                        "scenarios": scenarios,
                        "purge": purge,
                    }
                    for scenario in scenarios:
                        if scenario["artifact_dir"] is None:
                            continue
                        scenario_dir = args.output / scenario["artifact_dir"]
                        scenario_dir.mkdir(parents=True)
                        (scenario_dir / "result.json").write_text(
                            json.dumps(scenario), encoding="utf-8"
                        )
                    purge_dir = args.output / "purge"
                    purge_dir.mkdir()
                    (purge_dir / "result.json").write_text(json.dumps(purge), encoding="utf-8")
                if manifest_mode == "malformed":
                    (args.output / "manifest.json").write_text("[", encoding="utf-8")
                else:
                    (args.output / "manifest.json").write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
            raise SystemExit(runner_exit)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (production / "ci_result.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import argparse
            import os
            from pathlib import Path


            parser = argparse.ArgumentParser()
            parser.add_argument("--run-json", required=True, type=Path)
            parser.add_argument("--runner-exit-code", required=True, type=int)
            args = parser.parse_args()

            classifier_exit = int(os.environ.get("QUALITY_CLASSIFIER_EXIT", "0"))
            message = os.environ.get("QUALITY_CLASSIFIER_MESSAGE", "diagnostic classification")
            print(message)
            raise SystemExit(classifier_exit)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return fixture_root


def copy_live_install_sandbox_gate_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "repository"
    shutil.copytree(
        PROJECT_ROOT / "tools" / "install_sandbox",
        fixture_root / "tools" / "install_sandbox",
        ignore=shutil.ignore_patterns("__pycache__", "graphify-out", "out"),
    )
    shutil.copyfile(PROJECT_ROOT / "tools" / "__init__.py", fixture_root / "tools" / "__init__.py")
    for evidence_class in ("unit", "component"):
        shutil.copytree(
            PROJECT_ROOT / "tests" / "install_sandbox" / evidence_class,
            fixture_root / "tests" / "install_sandbox" / evidence_class,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    workflow = Path(".github/workflows/install-sandbox.yml")
    (fixture_root / workflow).parent.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / workflow, fixture_root / workflow)
    (fixture_root / ".venv").symlink_to(PROJECT_ROOT / ".venv", target_is_directory=True)
    shutil.copyfile(RUFF_CONFIG, fixture_root / RUFF_CONFIG.name)
    shutil.copyfile(PYRIGHT_CONFIG, fixture_root / PYRIGHT_CONFIG.name)
    return fixture_root


def copy_install_sandbox_gate_fixture(tmp_path: Path) -> Path:
    """Build the immutable closed-baseline state used by applicability proofs."""
    fixture_root = tmp_path / "repository"
    production = fixture_root / "tools/install_sandbox"
    production.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "tools" / "__init__.py", fixture_root / "tools" / "__init__.py")
    sources = {
        "__init__.py": '"""Fixed gate-installation fixture."""\n',
        "ci_result.py": "def main() -> int:\n    return 0\n",
        "docker.py": "def run_sandbox() -> None:\n    return None\n",
        "effects.py": '"""Legacy fixture module."""\n',
        "lifecycle.py": '"""Legacy fixture module."""\n',
        "models.py": '"""Legacy fixture module."""\n',
        "reporting.py": '"""Legacy fixture module."""\n',
        "run.py": (
            "from tools.install_sandbox.docker import run_sandbox\n"
            "from tools.install_sandbox.run_artifacts import write_run\n"
            "from tools.install_sandbox.specs import load_specs\n\n\n"
            "def main() -> int:\n"
            "    run_sandbox()\n"
            "    write_run()\n"
            "    load_specs()\n"
            "    return 0\n"
        ),
        "run_artifacts.py": "def write_run() -> None:\n    return None\n",
        "sandbox_runner.py": "def main() -> int:\n    return 0\n",
        "specs.py": "def load_specs() -> None:\n    return None\n",
    }
    for name, source in sources.items():
        (production / name).write_text(source, encoding="utf-8")
    specs = production / "specs"
    specs.mkdir()
    (specs / "catalog.yaml").write_text("targets: {}\n", encoding="utf-8")
    (production / "Dockerfile").write_text(
        'FROM python:3.12-slim\nENTRYPOINT ["python", "-m", '
        '"tools.install_sandbox.sandbox_runner"]\n',
        encoding="utf-8",
    )

    workflow = fixture_root / ".github/workflows/install-sandbox.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Install sandbox fixture\n"
        "jobs:\n"
        "  proof:\n"
        "    steps:\n"
        "      - run: uv run --frozen --python 3.12 python "
        "scripts/install_sandbox_quality.py complete\n",
        encoding="utf-8",
    )
    (fixture_root / RUFF_CONFIG.name).write_text(
        'target-version = "py312"\n'
        "line-length = 100\n"
        "preview = false\n\n"
        "[lint]\n"
        'select = ["E", "F", "I", "UP", "B", "SIM", "RUF", '
        '"C901", "PLR0912", "PLR0915"]\n\n'
        "[lint.mccabe]\n"
        "max-complexity = 8\n\n"
        "[lint.pylint]\n"
        "max-branches = 10\n"
        "max-statements = 30\n",
        encoding="utf-8",
    )
    analysis_paths = [
        "tools/install_sandbox",
        "tests/install_sandbox/unit",
        "tests/install_sandbox/component",
        "tests/install_sandbox/behavioral",
    ]
    (fixture_root / PYRIGHT_CONFIG.name).write_text(
        json.dumps(
            {
                "include": analysis_paths,
                "strict": analysis_paths,
                "pythonVersion": PYTHON_VERSION,
                "typeCheckingMode": "basic",
                "venvPath": ".",
                "venv": ".venv",
            }
        ),
        encoding="utf-8",
    )
    (fixture_root / ".venv").symlink_to(PROJECT_ROOT / ".venv", target_is_directory=True)
    return fixture_root


def copy_complete_gate_fixture(tmp_path: Path) -> Path:
    """Compose a valid gate-installation repository with real Docker evidence adapters."""

    fixture_root = copy_install_sandbox_gate_fixture(tmp_path)
    docker_fixture = copy_docker_gate_fixture(tmp_path / "docker-adapters")
    production = fixture_root / "tools/install_sandbox"

    docker_runner = (docker_fixture / "tools/install_sandbox/run.py").read_text(encoding="utf-8")
    state_only_calls = textwrap.dedent(
        """
        if False:
            from tools.install_sandbox import docker, run_artifacts, specs

            docker.run_sandbox()
            run_artifacts.write_run()
            specs.load_specs()

        """
    )
    (production / "run.py").write_text(
        docker_runner.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\n" + state_only_calls,
            1,
        ),
        encoding="utf-8",
    )
    shutil.copyfile(
        docker_fixture / "tools/install_sandbox/ci_result.py",
        production / "ci_result.py",
    )
    shutil.rmtree(production / "specs")
    shutil.copytree(docker_fixture / "tools/install_sandbox/specs", production / "specs")
    shutil.copytree(docker_fixture / "graphify", fixture_root / "graphify")

    exclusions = "\n".join(f'    "{path}",' for path in APPROVED_TEMPORARY_COVERAGE_EXCLUSIONS)
    (fixture_root / "pyproject.toml").write_text(
        '[project]\nname = "complete-gate-fixture"\nversion = "0"\n\n'
        "[tool.coverage.run]\n"
        "omit = [\n"
        f"{exclusions}\n"
        "]\n",
        encoding="utf-8",
    )
    (fixture_root / "uv.lock").write_text("fixture lock\n", encoding="utf-8")
    return fixture_root


def copy_prove_gate_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "repository"
    proof_root = fixture_root / "tests" / "quality_gate"
    proof_root.mkdir(parents=True)
    for source in sorted((PROJECT_ROOT / "tests" / "quality_gate").glob("test_*.py")):
        if source.name != "test_prove_gate.py":
            shutil.copyfile(source, proof_root / source.name)
    (fixture_root / "uv.lock").write_text("fixture lock\n", encoding="utf-8")
    return fixture_root


def install_fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    """Install a command-recording uv boundary that executes only Python children."""

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    command_log = tmp_path / "quality-commands.jsonl"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            from __future__ import annotations

            import json
            import os
            import sys
            from pathlib import Path


            arguments = sys.argv[1:]
            prefix = ["run", "--frozen", "--python", "{PYTHON_VERSION}"]
            if arguments[: len(prefix)] != prefix:
                print("unexpected uv arguments: " + repr(arguments), file=sys.stderr)
                raise SystemExit(2)
            command = arguments[len(prefix) :]
            log = Path(os.environ["QUALITY_COMMAND_LOG"])
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(command) + "\\n")

            if command and command[0] == "python":
                os.execv(sys.executable, [sys.executable, *command[1:]])

            rules = json.loads(os.environ.get("QUALITY_FAKE_COMMAND_RULES", "{{}}"))
            rendered = " ".join(command)
            matches = [key for key in rules if key in rendered]
            rule = rules[max(matches, key=len)] if matches else {{}}
            if stdout := rule.get("stdout"):
                print(stdout)
            if stderr := rule.get("stderr"):
                print(stderr, file=sys.stderr)
            if replacement := rule.get("lock_contents"):
                Path("uv.lock").write_text(replacement, encoding="utf-8")
            if (
                command[:2] == ["pytest", "tests/install_sandbox/behavioral"]
                and "--collect-only" in command
                and not any(
                    candidate.is_file()
                    for candidate in Path(command[1]).rglob("*")
                )
            ):
                raise SystemExit(5)
            raise SystemExit(int(rule.get("exit", 0)))
            """
        ),
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    return bin_dir, command_log


def run_complete_gate(
    tmp_path: Path,
    repository: Path,
    *,
    command_rules: dict[str, dict[str, object]] | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], tuple[tuple[str, ...], ...]]:
    bin_dir, command_log = install_fake_uv(tmp_path)
    child_environment = {
        "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
        "QUALITY_COMMAND_LOG": str(command_log),
        "QUALITY_FAKE_COMMAND_RULES": json.dumps(command_rules or {}),
    }
    if environment is not None:
        child_environment.update(environment)
    result = run_quality_gate(
        repository,
        arguments=("complete",),
        environment=child_environment,
    )
    commands = tuple(
        tuple(json.loads(line)) for line in command_log.read_text(encoding="utf-8").splitlines()
    )
    return result, commands


def run_prove_gate(
    tmp_path: Path,
    repository: Path,
    *,
    command_rules: dict[str, dict[str, object]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], tuple[tuple[str, ...], ...]]:
    bin_dir, command_log = install_fake_uv(tmp_path)
    result = run_quality_gate(
        repository,
        arguments=("prove",),
        environment={
            "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
            "QUALITY_COMMAND_LOG": str(command_log),
            "QUALITY_FAKE_COMMAND_RULES": json.dumps(command_rules or {}),
        },
    )
    commands = (
        tuple(
            tuple(json.loads(line)) for line in command_log.read_text(encoding="utf-8").splitlines()
        )
        if command_log.exists()
        else ()
    )
    return result, commands


def run_fast_gate(
    tmp_path: Path,
    source: str,
    *,
    ruff_config: str | None = None,
    filename: str = "reporting.py",
    replacement_source: str | None = None,
    pyright_config: str | None = None,
    bandit_config: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fixture_root = copy_live_install_sandbox_gate_fixture(tmp_path)
    production = fixture_root / "tools" / "install_sandbox"
    if filename == "reporting.py":
        source += (
            "\n\ndef build_manifest(*args: object, **kwargs: object) -> dict[str, object]:\n"
            "    return {}\n\n\n"
            "def write_run_outputs(*args: object, **kwargs: object) -> None:\n"
            "    return None\n"
        )
    (production / filename).write_text(source, encoding="utf-8")

    if replacement_source is not None:
        unit_tests = fixture_root / "tests" / "install_sandbox" / "unit"
        unit_tests.mkdir(parents=True, exist_ok=True)
        (unit_tests / "test_fixture.py").write_text(replacement_source, encoding="utf-8")
    if bandit_config is not None:
        (production / ".bandit").write_text(bandit_config, encoding="utf-8")

    fixture_ruff_config = fixture_root / RUFF_CONFIG.name
    if ruff_config is None:
        shutil.copyfile(RUFF_CONFIG, fixture_ruff_config)
    else:
        fixture_ruff_config.write_text(ruff_config, encoding="utf-8")
    fixture_pyright_config = fixture_root / PYRIGHT_CONFIG.name
    if pyright_config is None:
        shutil.copyfile(PYRIGHT_CONFIG, fixture_pyright_config)
    else:
        fixture_pyright_config.write_text(pyright_config, encoding="utf-8")

    return run_quality_gate(fixture_root)
