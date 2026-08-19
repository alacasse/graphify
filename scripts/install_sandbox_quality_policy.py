"""Static-analysis scope and finite-exception policy for the install sandbox gate."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import tokenize
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from install_sandbox_quality_state import GatePhase

PYRIGHT_CONFIG = "pyrightconfig.install-sandbox.json"
INSTALL_SANDBOX = "tools/install_sandbox"
PYTHON_VERSION = "3.12"
REPLACEMENT_TEST_PATHS = (
    "tests/install_sandbox/unit",
    "tests/install_sandbox/component",
    "tests/install_sandbox/behavioral",
)
PYPROJECT_CONFIG = "pyproject.toml"
TEMPORARY_COVERAGE_EXCLUSIONS = (
    f"{INSTALL_SANDBOX}/ci_result.py",
    f"{INSTALL_SANDBOX}/docker.py",
    f"{INSTALL_SANDBOX}/effects.py",
    f"{INSTALL_SANDBOX}/lifecycle.py",
    f"{INSTALL_SANDBOX}/models.py",
    f"{INSTALL_SANDBOX}/reporting.py",
    f"{INSTALL_SANDBOX}/run.py",
    f"{INSTALL_SANDBOX}/run_artifacts.py",
    f"{INSTALL_SANDBOX}/sandbox_runner.py",
    f"{INSTALL_SANDBOX}/specs.py",
)
LEGACY_TYPING_FILES = frozenset(
    {
        f"{INSTALL_SANDBOX}/ci_result.py",
        f"{INSTALL_SANDBOX}/effects.py",
        f"{INSTALL_SANDBOX}/lifecycle.py",
        f"{INSTALL_SANDBOX}/models.py",
        f"{INSTALL_SANDBOX}/run.py",
        f"{INSTALL_SANDBOX}/run_artifacts.py",
        f"{INSTALL_SANDBOX}/sandbox_runner.py",
        f"{INSTALL_SANDBOX}/specs.py",
    }
)
LEGACY_TYPING_AST_FINGERPRINTS = {
    "ci_result.py": "65e3207460cb20a707997a6e88230cbaf86e3d7dc9f44c6921786f7992368e85",
    "effects.py": "806bed5536360b7e4027bf046253d8803b54378d5ce1e282382565bed6704123",
    "lifecycle.py": "237ffd31bc012c069d9b026602e1d791668514c42fe872477e6a5a351beaad36",
    "models.py": "3c5aea03ea372eff699741d530f8f456e5241c814a249aeb3c13415f475b9e9c",
    "run.py": "055d9dc205b5293d8f108d7829829992a3d7e7dcd03ebabd3ba5cd13261280dc",
    "run_artifacts.py": "25aaa6c8e2b1679f7f7aeb7f5c9e472b7544d91575aab487a355cc61010c4e66",
    "sandbox_runner.py": "60892e468253bb4235ffc52ff4d12928538ef988db4d62ac10f7313d83d7ab5a",
    "specs.py": "13d21c1ded61b625887ee795aafc8c8b3edf7fd512ae89b70c65904f3d521b3c",
}
PYRIGHT_CONFIG_KEYS = frozenset(
    {"include", "strict", "pythonVersion", "typeCheckingMode", "venvPath", "venv"}
)
PYRIGHT_DIRECTIVE = re.compile(r"#\s*pyright\s*:", re.IGNORECASE)
TYPING_AFFECTING_COMMENT = re.compile(r"#\s*(?:pyright\s*:|type\s*:)", re.IGNORECASE)
NOSEC_DIRECTIVE = re.compile(r"#\s*nosec", re.IGNORECASE)


@dataclass(frozen=True)
class SecurityDisposition:
    source_path: str
    source_line: str
    occurrences: int = 1


APPROVED_BANDIT_DISPOSITIONS = (
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/docker.py",
        'CONTAINER_HOME = "/tmp/graphify-home"  # nosec B108',
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/docker.py",
        'CONTAINER_XDG = "/tmp/graphify-xdg"  # nosec B108',
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/docker.py",
        'CONTAINER_PROJECT = "/tmp/graphify-project"  # nosec B108',
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/docker.py",
        'CONTAINER_USER_CWD = "/tmp/graphify-user-cwd"  # nosec B108',
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/docker.py",
        'CONTAINER_SOURCE = "/tmp/graphify-source"  # nosec B108',
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/lifecycle.py",
        'result = execute_command(argv, Path("/tmp"), env, package_dir, "pip-install")'
        "  # nosec B108",
    ),
    SecurityDisposition(
        f"{INSTALL_SANDBOX}/lifecycle.py",
        'Path("/tmp"),  # nosec B108',
        occurrences=2,
    ),
)


def _path_is_covered(relative: Path, configured_paths: tuple[Path, ...]) -> bool:
    return any(relative == path or path in relative.parents for path in configured_paths)


def _typing_fingerprint(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source))
    serialized = ast.dump(tree, include_attributes=False)
    typing_comments = tuple(
        comment.strip()
        for _, comment in _comment_tokens_from_text(text)
        if TYPING_AFFECTING_COMMENT.match(comment)
    )
    if typing_comments:
        serialized += repr(typing_comments)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _comment_tokens_from_text(text: str) -> tuple[tuple[int, str], ...]:
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return tuple(
        (token.start[0], token.string) for token in tokens if token.type == tokenize.COMMENT
    )


def _comment_tokens(source: Path) -> tuple[tuple[int, str], ...]:
    return _comment_tokens_from_text(source.read_text(encoding="utf-8"))


def _pyright_settings_error(config: dict[str, object]) -> str | None:
    unexpected = sorted(set(config) - PYRIGHT_CONFIG_KEYS)
    if unexpected:
        return f"{PYRIGHT_CONFIG}: unapproved settings: {', '.join(unexpected)}"
    if config.get("pythonVersion") != PYTHON_VERSION:
        return f"{PYRIGHT_CONFIG}: Pyright runtime must remain Python {PYTHON_VERSION}"
    if config.get("typeCheckingMode") != "basic":
        return f"{PYRIGHT_CONFIG}: default typing mode must remain basic"
    if config.get("venvPath") != ".":
        return f"{PYRIGHT_CONFIG}: Pyright environment root must remain ."
    if config.get("venv") != ".venv":
        return f"{PYRIGHT_CONFIG}: Pyright environment must remain .venv"
    return None


def _configuration_paths(config: dict[str, object], key: str) -> tuple[Path, ...]:
    values = config.get(key)
    if not isinstance(values, list) or not all(isinstance(path, str) for path in values):
        raise ValueError(f"{PYRIGHT_CONFIG}: {key} must be a list of paths")
    return tuple(Path(path) for path in values)


def _required_scope_error(
    configured_paths: tuple[Path, ...],
    required_paths: tuple[str, ...],
    label: str,
) -> str | None:
    for required in required_paths:
        if not _path_is_covered(Path(required), configured_paths):
            return f"{label} scope does not cover {required}"
    return None


def _legacy_typing_policy_error() -> str | None:
    fingerprinted = frozenset(
        f"{INSTALL_SANDBOX}/{name}" for name in LEGACY_TYPING_AST_FINGERPRINTS
    )
    if fingerprinted != LEGACY_TYPING_FILES:
        return "legacy typing filenames and fingerprints do not match"
    return None


def _legacy_typing_scope_error(
    source: Path,
    relative: Path,
    strict_paths: tuple[Path, ...],
) -> str | None:
    if _path_is_covered(relative, strict_paths):
        return None
    relative_text = relative.as_posix()
    try:
        current = _typing_fingerprint(source)
    except (OSError, SyntaxError, tokenize.TokenError) as error:
        return f"unable to verify legacy typing scope for {relative_text}: {error}"
    if current != LEGACY_TYPING_AST_FINGERPRINTS[relative.name]:
        return f"changed legacy typing file is not strict: {relative_text}"
    return None


def _production_strict_scope_error(
    repository: Path,
    strict_paths: tuple[Path, ...],
) -> str | None:
    production = repository / INSTALL_SANDBOX
    for source in sorted(production.rglob("*.py")):
        relative = source.relative_to(repository)
        relative_text = relative.as_posix()
        if relative_text in LEGACY_TYPING_FILES:
            error = _legacy_typing_scope_error(source, relative, strict_paths)
            if error is not None:
                return error
        elif not _path_is_covered(relative, strict_paths):
            return f"strict scope does not cover {relative_text}"
    return None


def _strict_source_directive_error(
    repository: Path,
    strict_paths: tuple[Path, ...],
) -> str | None:
    inspected: set[Path] = set()
    for configured_path in strict_paths:
        root = repository / configured_path
        sources = (root,) if root.is_file() else tuple(sorted(root.rglob("*.py")))
        for source in sources:
            if source in inspected:
                continue
            inspected.add(source)
            try:
                comments = _comment_tokens(source)
            except (OSError, IndentationError, tokenize.TokenError) as error:
                return f"unable to verify Pyright directives for {source}: {error}"
            for line_number, comment in comments:
                if PYRIGHT_DIRECTIVE.match(comment):
                    relative = source.relative_to(repository).as_posix()
                    return f"unapproved Pyright directive: {relative}:{line_number}"
    return None


def typing_configuration_error(repository: Path) -> str | None:
    config_path = repository / PYRIGHT_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return f"unable to read {PYRIGHT_CONFIG}: {error}"
    if not isinstance(config, dict):
        return f"{PYRIGHT_CONFIG}: top level must be an object"
    error = _pyright_settings_error(config) or _legacy_typing_policy_error()
    if error is not None:
        return error
    try:
        include_paths = _configuration_paths(config, "include")
        strict_paths = _configuration_paths(config, "strict")
    except ValueError as error:
        return str(error)
    error = _required_scope_error(
        include_paths,
        (INSTALL_SANDBOX, *REPLACEMENT_TEST_PATHS),
        "analysis",
    )
    if error is not None:
        return error
    error = _required_scope_error(strict_paths, REPLACEMENT_TEST_PATHS, "strict")
    if error is not None:
        return error
    error = _production_strict_scope_error(repository, strict_paths)
    if error is not None:
        return error
    return _strict_source_directive_error(repository, strict_paths)


def _approved_bandit_counts() -> Counter[tuple[str, str]]:
    return Counter(
        {
            (disposition.source_path, disposition.source_line): disposition.occurrences
            for disposition in APPROVED_BANDIT_DISPOSITIONS
        }
    )


def _discovered_bandit_configuration(repository: Path) -> Path | None:
    candidates = [repository / ".bandit"]
    candidates.extend((repository / INSTALL_SANDBOX).rglob(".bandit"))
    return next((path for path in candidates if path.exists()), None)


def security_configuration_error(repository: Path) -> str | None:
    discovered = _discovered_bandit_configuration(repository)
    if discovered is not None:
        relative = discovered.relative_to(repository).as_posix()
        return f"discovered Bandit configuration is not permitted: {relative}"

    approved = _approved_bandit_counts()
    actual: Counter[tuple[str, str]] = Counter()
    production = repository / INSTALL_SANDBOX
    for source in sorted(production.rglob("*.py")):
        relative = source.relative_to(repository).as_posix()
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
            comments = _comment_tokens(source)
        except (OSError, IndentationError, tokenize.TokenError) as error:
            return f"unable to verify Bandit dispositions for {relative}: {error}"
        for line_number, comment in comments:
            if NOSEC_DIRECTIVE.search(comment):
                actual[(relative, lines[line_number - 1].strip())] += 1

    for disposition, occurrences in actual.items():
        if occurrences > approved[disposition]:
            return f"unapproved Bandit disposition: {disposition[0]}"
    return None


def _configuration_table(
    value: object,
    label: str,
    *,
    optional: bool,
) -> tuple[dict[str, object] | None, str | None]:
    if value is None and optional:
        return None, None
    if not isinstance(value, dict):
        return None, f"{PYPROJECT_CONFIG}: missing {label} policy"
    return value, None


def _unexpected_settings_error(
    config: dict[str, object],
    allowed: set[str],
    label: str,
) -> str | None:
    unexpected = sorted(set(config) - allowed)
    if not unexpected:
        return None
    return f"{PYPROJECT_CONFIG}: unapproved {label} settings: {', '.join(unexpected)}"


def coverage_configuration_error(repository: Path, phase: GatePhase) -> str | None:
    """Reject coverage configuration that can hide replacement production paths."""

    config_path = repository / PYPROJECT_CONFIG
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return f"unable to read {PYPROJECT_CONFIG}: {error}"

    optional = phase is GatePhase.ATOMIC_CUTOVER
    tool = config.get("tool")
    coverage_value = tool.get("coverage") if isinstance(tool, dict) else None
    coverage, error = _configuration_table(
        coverage_value,
        "tool.coverage",
        optional=optional,
    )
    if error is not None or coverage is None:
        return error
    error = _unexpected_settings_error(coverage, {"run"}, "tool.coverage")
    if error is not None:
        return error

    run, error = _configuration_table(
        coverage.get("run"),
        "tool.coverage.run",
        optional=optional,
    )
    if error is not None or run is None:
        return error
    error = _unexpected_settings_error(run, {"omit"}, "tool.coverage.run")
    if error is not None:
        return error

    raw_omit = run.get("omit", [])
    if not isinstance(raw_omit, list) or not all(isinstance(path, str) for path in raw_omit):
        return f"{PYPROJECT_CONFIG}: tool.coverage.run.omit must be a list of paths"
    actual = tuple(raw_omit)
    expected = () if phase is GatePhase.ATOMIC_CUTOVER else TEMPORARY_COVERAGE_EXCLUSIONS
    if actual != expected:
        state = "empty at Atomic Cutover" if not expected else "the exact legacy retirement list"
        return f"{PYPROJECT_CONFIG}: coverage exclusions must be {state}"
    return None
