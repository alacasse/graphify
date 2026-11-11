"""Discover the full catalog while preserving converted tools and their scopes."""

import subprocess
from pathlib import Path

import yaml

from tools.install_sandbox.contracts.effects import ToolDeclaration
from tools.install_sandbox.host.effect_reader import EffectSpecReader

ROOT = Path(__file__).resolve().parents[4]
SPECS = Path("tools/install_sandbox/specs")
BASELINE = "df44955b"


def conversion_baseline() -> tuple[dict[Path, bytes], dict[tuple[str, str], str | None]]:
    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout

    legacy: dict[Path, bytes] = {}
    required: dict[tuple[str, str], str | None] = {}
    historical_paths = git("ls-tree", "-r", "--name-only", BASELINE, SPECS.as_posix())
    for name in historical_paths.decode().splitlines():
        path = Path(name)
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        payload = git("show", f"{BASELINE}:{name}")
        raw = yaml.safe_load(payload)
        if "tool" not in raw:
            legacy[path] = payload.replace(b"\r\n", b"\n")
        else:
            for scope, value in raw["scopes"].items():
                required[raw["tool"], scope] = value["state"] if isinstance(value, dict) else None
    return legacy, required


def test_repository_catalog_is_readable_and_preserves_declared_scopes() -> None:
    legacy, required = conversion_baseline()
    reader = EffectSpecReader()
    paths = sorted(
        path for path in (ROOT / SPECS).rglob("*") if path.suffix.lower() in {".yaml", ".yml"}
    )
    assert paths, "No sandbox specs discovered"
    converted: dict[str, ToolDeclaration] = {}
    for path in paths:
        try:
            declaration = reader.read(path)
        except ValueError as error:
            assert "Historical spec has not been converted" in str(error), path
            relative = path.relative_to(ROOT)
            # A checkout may use CRLF. Compare all other bytes as read by the CLI.
            content = path.read_bytes().replace(b"\r\n", b"\n")
            assert content == legacy.get(relative), f"Unconverted spec changed or added: {path}"
        else:
            assert declaration.tool == path.stem, f"Tool/file mismatch: {path}"
            assert declaration.tool not in converted, f"Duplicate tool: {declaration.tool}"
            assert ToolDeclaration.from_data(declaration.to_data()) == declaration
            converted[declaration.tool] = declaration

    for (tool, scope), previous_state in required.items():
        assert tool in converted, f"Converted tool removed or reverted to legacy: {tool}"
        states = {item.scope: item.classification for item in converted[tool].scopes}
        assert scope in states, f"Declared scope removed: {tool}/{scope}"
        assert states[scope] in (None, previous_state), (
            f"Declared scope lost its executable effects or obligation: {tool}/{scope}"
        )
