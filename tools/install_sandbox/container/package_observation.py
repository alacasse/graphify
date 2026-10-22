"""Observe the installed package without invoking the product's installer or CLI."""

import base64
import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import cast


def _resources(root: Path, errors: list[str]) -> tuple[dict[str, str], list[str]]:
    resources: dict[str, str] = {}
    directories: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            errors.append(f"Installed resource is a symlink: {relative}")
        elif path.is_dir():
            directories.append(relative)
        elif path.is_file():
            resources[relative] = base64.b64encode(path.read_bytes()).decode("ascii")
    return resources, directories


def _package(
    declaration: dict[str, object], errors: list[str]
) -> tuple[dict[str, object], set[Path]]:
    distribution = importlib.metadata.distribution(str(declaration["distribution"]))
    entries = [
        entry
        for entry in distribution.entry_points
        if entry.group == "console_scripts" and entry.name == declaration["console"]
    ]
    module_name = str(declaration["entry_point"]).split(":", 1)[0]
    module = importlib.import_module(module_name)
    module_file = Path(cast(str, module.__file__)).resolve(strict=True)
    package_name = str(declaration["package_root"]).replace("/", ".")
    package = importlib.import_module(package_name)
    root = Path(cast(str, package.__file__)).resolve(strict=True).parent
    owned = {Path(str(distribution.locate_file(f))).resolve() for f in distribution.files or ()}
    resources, directories = _resources(root, errors)
    return {
        "distribution": distribution.metadata["Name"],
        "version": distribution.version,
        "entry_point": entries[0].value if len(entries) == 1 else "",
        "module": str(module_file),
        "source_root": str(root),
        "resources": resources,
        "directories": directories,
        "module_owned": module_file in owned,
    }, owned


def _executable(
    executable: str,
    entry_point: str,
    owned: set[Path],
    errors: list[str],
) -> dict[str, object]:
    try:
        path = Path(executable)
        script = path.read_bytes()
        shebang = script.decode("utf-8").splitlines()[0]
        # Resolve only the embedded sandbox when launched as an isolated script.
        if __package__ in {None, ""}:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from tools.install_sandbox.contracts.script_identity import console_wrapper_matches

        return {
            "executable_shebang": shebang,
            "executable_owned": path.resolve() in owned,
            "executable_entry_point": console_wrapper_matches(script, entry_point),
            "executable_script": base64.b64encode(script).decode("ascii"),
            "executable_regular": path.is_file()
            and os.access(path, os.X_OK)
            and not path.is_symlink(),
        }
    except (OSError, UnicodeError, IndexError) as error:
        errors.append(f"Executable observation failed: {error}")
        return {
            "executable_shebang": "",
            "executable_script": "",
            "executable_owned": False,
            "executable_entry_point": False,
            "executable_regular": False,
        }


def observe(inputs: Path, output: Path, executable: str) -> None:
    """Record package bytes and provenance from this interpreter's installation."""
    declaration = cast(dict[str, object], json.loads(inputs.read_text(encoding="utf-8")))
    errors: list[str] = []
    owned: set[Path] = set()
    observation: dict[str, object] = {
        "format": "preparation-observation-v1",
        "image_id": os.environ.get("INSTALL_SANDBOX_IMAGE_ID", ""),
        "distribution": declaration["distribution"],
        "version": "",
        "entry_point": "",
        "interpreter": sys.executable,
        "executable": executable,
        "module": "",
        "source_root": "",
        "resources": {},
        "directories": [],
        "module_owned": False,
        "errors": errors,
    }
    try:
        package, owned = _package(declaration, errors)
        observation.update(package)
    except Exception as error:
        errors.append(f"Package observation failed: {type(error).__name__}: {error}")
    observation.update(_executable(executable, str(declaration["entry_point"]), owned, errors))
    (output / "observation.json").write_text(
        json.dumps(observation, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    observe(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
