"""Repository-derived evidence applicability for the install-sandbox gate."""

from __future__ import annotations

import ast
import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import cast

import yaml

from scripts.install_sandbox_quality_phase import GatePhase

INSTALL_SANDBOX = Path("tools/install_sandbox")
WORKFLOW = Path(".github/workflows/install-sandbox.yml")
QUALITY_SCRIPT = "scripts/install_sandbox_quality.py"
CANONICAL_COMPLETE_COMMAND = (
    "uv",
    "run",
    "--frozen",
    "--python",
    "3.12",
    "python",
    QUALITY_SCRIPT,
    "complete",
)

FIXED_BASELINE_PRODUCTION_PATHS = frozenset(
    INSTALL_SANDBOX / name
    for name in (
        "__init__.py",
        "ci_result.py",
        "docker.py",
        "effects.py",
        "lifecycle.py",
        "models.py",
        "reporting.py",
        "run.py",
        "run_artifacts.py",
        "sandbox_runner.py",
        "specs.py",
    )
)
LEGACY_IMPLEMENTATION_PATHS = FIXED_BASELINE_PRODUCTION_PATHS - {
    INSTALL_SANDBOX / "__init__.py",
    INSTALL_SANDBOX / "run.py",
}
LEGACY_MODULE_NAMES = frozenset(path.stem for path in LEGACY_IMPLEMENTATION_PATHS)
FINAL_REQUIRED_PATHS = frozenset(
    {
        INSTALL_SANDBOX / "__init__.py",
        INSTALL_SANDBOX / "run.py",
        INSTALL_SANDBOX / "ci.py",
        INSTALL_SANDBOX / "container/entrypoint.py",
    }
)


@dataclass(frozen=True)
class RepositoryState:
    phase: GatePhase
    static_analysis_paths: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryStateFailure:
    problems: tuple[str, ...]


type RepositoryStateAssessment = RepositoryState | RepositoryStateFailure


def _read_text(repository: Path, relative: Path) -> str | None:
    try:
        return (repository / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _production_paths(repository: Path) -> frozenset[Path]:
    production_root = repository / INSTALL_SANDBOX
    return frozenset(source.relative_to(repository) for source in production_root.rglob("*.py"))


def _absolute_import_module(node: ast.ImportFrom, package: str) -> str:
    imported_module = node.module or ""
    if not node.level:
        return imported_module
    parent_parts = package.split(".")[: -(node.level - 1) or None]
    return ".".join((*parent_parts, imported_module)).rstrip(".")


def _callable_path(function: ast.expr, bindings: dict[str, str]) -> str | None:
    parts: list[str] = []
    current = function
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return ".".join((bindings.get(parts[0], parts[0]), *parts[1:]))


def _import_bindings(tree: ast.AST, package: str) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                bindings[local_name] = alias.name if alias.asname else local_name
        elif isinstance(node, ast.ImportFrom):
            imported_module = _absolute_import_module(node, package)
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{imported_module}.{alias.name}"
    return bindings


def _calls_module(source: str, module: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    bindings = _import_bindings(tree, "tools.install_sandbox")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _callable_path(node.func, bindings)
        if called == module or (called is not None and called.startswith(f"{module}.")):
            return True
    return False


def _docker_entrypoint_module(source: str | None) -> str | None:
    if source is None:
        return None
    entrypoint: str | None = None
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ENTRYPOINT"):
            continue
        try:
            arguments = json.loads(stripped.removeprefix("ENTRYPOINT").strip())
        except json.JSONDecodeError:
            entrypoint = None
            continue
        if (
            isinstance(arguments, list)
            and len(arguments) >= 3
            and arguments[:2] == ["python", "-m"]
            and isinstance(arguments[2], str)
        ):
            entrypoint = arguments[2]
        else:
            entrypoint = None
    return entrypoint


def _shell_commands(source: str | None) -> tuple[str, ...]:
    if source is None:
        return ()
    commands: list[str] = []
    continued: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fragment = stripped.removesuffix("\\").strip()
        if continued or stripped.endswith("\\"):
            continued.append(fragment)
            if not stripped.endswith("\\"):
                commands.append(" ".join(continued))
                continued = []
        else:
            commands.append(fragment)
    if continued:
        commands.append(" ".join(continued))
    return tuple(commands)


def _step_run_block(step: object) -> str | None:
    if not isinstance(step, Mapping):
        return None
    run = step.get("run")
    return run if isinstance(run, str) else None


def _job_run_blocks(job: object) -> tuple[str, ...]:
    if not isinstance(job, Mapping):
        return ()
    steps = job.get("steps")
    if not isinstance(steps, list):
        return ()
    return tuple(filter(None, (_step_run_block(step) for step in steps)))


def _workflow_run_blocks(source: str | None) -> tuple[str, ...]:
    if source is None:
        return ()
    try:
        document = cast(object, yaml.safe_load(source))
    except yaml.YAMLError:
        return ()
    if not isinstance(document, Mapping):
        return ()
    jobs = document.get("jobs")
    if not isinstance(jobs, Mapping):
        return ()
    return tuple(run_block for job in jobs.values() for run_block in _job_run_blocks(job))


def _workflow_commands(source: str | None) -> tuple[str, ...]:
    return tuple(
        command
        for run_block in _workflow_run_blocks(source)
        for command in _shell_commands(run_block)
    )


def _command_invokes_script(command: str, script: str) -> bool:
    return re.search(rf"(?:^|\s)python\s+{re.escape(script)}(?:\s|$)", command) is not None


def _command_invokes_module(command: str, module: str) -> bool:
    return re.search(rf"(?:^|\s)python\s+-m\s+{re.escape(module)}(?:\s|$)", command) is not None


def _workflow_host_commands(workflow: str | None) -> tuple[str, ...]:
    script = "tools/install_sandbox/run.py"
    return tuple(
        command
        for command in _workflow_commands(workflow)
        if _command_invokes_script(command, script)
    )


def _workflow_invokes_module(workflow: str | None, module: str) -> bool:
    return any(_command_invokes_module(command, module) for command in _workflow_commands(workflow))


def _is_canonical_complete_command(command: str) -> bool:
    try:
        return tuple(shlex.split(command)) == CANONICAL_COMPLETE_COMMAND
    except ValueError:
        return False


def _workflow_quality_owner_problems(workflow: str | None) -> tuple[str, ...]:
    commands = _workflow_commands(workflow)
    problems: list[str] = []
    if not any(_is_canonical_complete_command(command) for command in commands):
        problems.append("workflow does not invoke the canonical complete quality command")
    if _workflow_host_commands(workflow) or any(
        _workflow_invokes_module(workflow, module)
        for module in ("tools.install_sandbox.ci_result", "tools.install_sandbox.ci")
    ):
        problems.append("workflow bypasses the canonical quality command owner")
    return tuple(problems)


def _legacy_caller_problems(repository: Path) -> tuple[str, ...]:
    problems: list[str] = []
    run_source = _read_text(repository, INSTALL_SANDBOX / "run.py")
    if run_source is None or not all(
        _calls_module(run_source, module)
        for module in (
            "tools.install_sandbox.docker",
            "tools.install_sandbox.run_artifacts",
            "tools.install_sandbox.specs",
        )
    ):
        problems.append("operator caller does not point to the complete legacy host entrypoint")

    dockerfile = _read_text(repository, INSTALL_SANDBOX / "Dockerfile")
    if _docker_entrypoint_module(dockerfile) != "tools.install_sandbox.sandbox_runner":
        problems.append("harness-image caller does not point to the legacy container entrypoint")

    workflow = _read_text(repository, WORKFLOW)
    problems.extend(_workflow_quality_owner_problems(workflow))
    return tuple(problems)


def _replacement_caller_problems(repository: Path) -> tuple[str, ...]:
    problems: list[str] = []
    run_source = _read_text(repository, INSTALL_SANDBOX / "run.py")
    if run_source is None or not _calls_module(run_source, "tools.install_sandbox.control_plane"):
        problems.append("operator caller does not invoke the replacement Host Control Plane")

    old_dockerfile = repository / INSTALL_SANDBOX / "Dockerfile"
    containerfile = _read_text(repository, INSTALL_SANDBOX / "Containerfile")
    old_dockerfile_remains = old_dockerfile.exists() or old_dockerfile.is_symlink()
    if old_dockerfile_remains or _docker_entrypoint_module(containerfile) != (
        "tools.install_sandbox.container.entrypoint"
    ):
        problems.append("harness-image caller does not point only to the replacement entrypoint")

    workflow = _read_text(repository, WORKFLOW)
    problems.extend(_workflow_quality_owner_problems(workflow))
    return tuple(problems)


def _is_legacy_module(module: str, *, relative: bool = False) -> bool:
    parts = module.split(".")
    if relative:
        return bool(parts) and parts[0] in LEGACY_MODULE_NAMES
    prefix = ("tools", "install_sandbox")
    return tuple(parts[:2]) == prefix and len(parts) > 2 and parts[2] in LEGACY_MODULE_NAMES


def _legacy_imports(source: Path, *, allow_relative: bool) -> tuple[str, ...]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError, UnicodeError) as error:
        return (f"cannot inspect imports in {source}: {error}",)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(name.name for name in node.names if _is_legacy_module(name.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_legacy_module(
                module,
                relative=allow_relative and node.level > 0,
            ):
                found.add(module)
            if module == "tools.install_sandbox" or (
                allow_relative and node.level > 0 and module == ""
            ):
                found.update(name.name for name in node.names if name.name in LEGACY_MODULE_NAMES)
    return tuple(sorted(found))


def _literal_string(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    return None


def _legacy_import_invocation(node: ast.Call, bindings: dict[str, str]) -> str | None:
    import_callables = {"__import__", "importlib.import_module", "runpy.run_module"}
    if _callable_path(node.func, bindings) not in import_callables or not node.args:
        return None
    module = _literal_string(node.args[0])
    return module if module is not None and _is_legacy_module(module) else None


def _legacy_modules_in_argument(argument: ast.expr) -> tuple[str, ...]:
    if isinstance(argument, (ast.List, ast.Tuple)):
        values = tuple(filter(None, (_literal_string(item) for item in argument.elts)))
        return tuple(
            module
            for marker, module in pairwise(values)
            if marker == "-m" and _is_legacy_module(module)
        )
    command = _literal_string(argument)
    if command is None:
        return ()
    return tuple(
        module
        for module in re.findall(r"(?:^|\s)-m\s+([\w.]+)", command)
        if _is_legacy_module(module)
    )


def _is_command_execution_callable(callable_path: str | None) -> bool:
    if callable_path is None:
        return False
    exact_callables = {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.popen",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.run",
    }
    return (
        callable_path in exact_callables
        or callable_path.startswith("os.exec")
        or callable_path.startswith("os.spawn")
    )


def _legacy_invocations(source: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError, UnicodeError):
        return ()
    bindings = _import_bindings(tree, "")
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        imported = _legacy_import_invocation(node, bindings)
        if imported is not None:
            found.add(imported)
        if not _is_command_execution_callable(_callable_path(node.func, bindings)):
            continue
        arguments = (*node.args, *(keyword.value for keyword in node.keywords))
        for argument in arguments:
            found.update(_legacy_modules_in_argument(argument))
    return tuple(sorted(found))


def _legacy_command_modules(source: str | None) -> tuple[str, ...]:
    legacy_modules = tuple(
        f"tools.install_sandbox.{module}" for module in sorted(LEGACY_MODULE_NAMES)
    )
    return tuple(
        module
        for module in legacy_modules
        if any(_command_invokes_module(command, module) for command in _shell_commands(source))
    )


def _forbidden_legacy_command_problems(repository: Path) -> tuple[str, ...]:
    problems: list[str] = []
    workflows = repository / ".github/workflows"
    workflow_files = set(workflows.glob("*.yml")) | set(workflows.glob("*.yaml"))
    for source in sorted(workflow_files):
        modules = {
            module
            for run_block in _workflow_run_blocks(
                _read_text(repository, source.relative_to(repository))
            )
            for module in _legacy_command_modules(run_block)
        }
        if modules:
            relative = source.relative_to(repository).as_posix()
            problems.append(
                f"forbidden legacy invocation in {relative}: {', '.join(sorted(modules))}"
            )
    command_files: set[Path] = set()
    for root_name in ("scripts", "tools"):
        command_files.update((repository / root_name).rglob("*.sh"))
    for source in sorted(command_files):
        modules = _legacy_command_modules(_read_text(repository, source.relative_to(repository)))
        if modules:
            relative = source.relative_to(repository).as_posix()
            problems.append(f"forbidden legacy invocation in {relative}: {', '.join(modules)}")
    container_files = tuple((repository / "tools").rglob("Dockerfile")) + tuple(
        (repository / "tools").rglob("Containerfile")
    )
    for source in sorted(container_files):
        module = _docker_entrypoint_module(_read_text(repository, source.relative_to(repository)))
        if module is not None and _is_legacy_module(module):
            relative = source.relative_to(repository).as_posix()
            problems.append(f"forbidden legacy invocation in {relative}: {module}")
    return tuple(problems)


def _forbidden_legacy_reference_problems(repository: Path) -> tuple[str, ...]:
    problems: list[str] = []
    roots = tuple(repository / root for root in ("graphify", "scripts", "tests", "tools"))
    sources = set(repository.glob("*.py"))
    for root in roots:
        sources.update(root.rglob("*.py"))
    production_root = repository / INSTALL_SANDBOX
    for source in sorted(sources):
        references = _legacy_imports(
            source,
            allow_relative=source.is_relative_to(production_root),
        )
        if references:
            relative = source.relative_to(repository).as_posix()
            problems.append(f"forbidden legacy import in {relative}: {', '.join(references)}")
        invocations = _legacy_invocations(source)
        if invocations:
            relative = source.relative_to(repository).as_posix()
            problems.append(f"forbidden legacy invocation in {relative}: {', '.join(invocations)}")
    problems.extend(_forbidden_legacy_command_problems(repository))
    return tuple(problems)


def _cutover_state_problems(repository: Path, production_paths: frozenset[Path]) -> tuple[str, ...]:
    problems: list[str] = []
    remaining = sorted(LEGACY_IMPLEMENTATION_PATHS & production_paths)
    if remaining:
        problems.append(
            "legacy implementation paths remain: "
            + ", ".join(path.as_posix() for path in remaining)
        )
    missing = sorted(FINAL_REQUIRED_PATHS - production_paths)
    if missing:
        problems.append(
            "missing final production paths: " + ", ".join(path.as_posix() for path in missing)
        )
    problems.extend(_replacement_caller_problems(repository))
    problems.extend(_forbidden_legacy_reference_problems(repository))
    return tuple(problems)


def assess_repository_state(repository: Path) -> RepositoryStateAssessment:
    """Classify the closed repository state from production and caller facts."""
    production_paths = _production_paths(repository)
    legacy_inventory_intact = production_paths >= FIXED_BASELINE_PRODUCTION_PATHS
    legacy_caller_problems = _legacy_caller_problems(repository)
    if legacy_inventory_intact and not legacy_caller_problems:
        replacement_paths = production_paths - FIXED_BASELINE_PRODUCTION_PATHS
        if not replacement_paths:
            return RepositoryState(
                phase=GatePhase.GATE_INSTALLATION,
                static_analysis_paths=(INSTALL_SANDBOX.as_posix(),),
            )
        return RepositoryState(
            phase=GatePhase.REPLACEMENT_CONSTRUCTION,
            static_analysis_paths=(
                INSTALL_SANDBOX.as_posix(),
                "tests/install_sandbox/unit",
                "tests/install_sandbox/component",
            ),
        )

    cutover_problems = _cutover_state_problems(repository, production_paths)
    if not cutover_problems:
        return RepositoryState(
            phase=GatePhase.ATOMIC_CUTOVER,
            static_analysis_paths=(
                INSTALL_SANDBOX.as_posix(),
                "tests/install_sandbox/unit",
                "tests/install_sandbox/component",
                "tests/install_sandbox/behavioral",
            ),
        )

    details = legacy_caller_problems if legacy_inventory_intact else cutover_problems
    return RepositoryStateFailure(("mixed repository state", *details))
