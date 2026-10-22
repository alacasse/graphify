"""Replay preparation evidence without a checkout, executable, or image."""

import base64
import binascii
import json
from pathlib import Path, PurePosixPath
from typing import cast

from tools.install_sandbox.contracts.effect_case import SubjectContext
from tools.install_sandbox.contracts.effects import EffectSpec, SkillEffect
from tools.install_sandbox.contracts.preparation import PreparationResult
from tools.install_sandbox.contracts.script_identity import console_wrapper_matches
from tools.install_sandbox.contracts.spec import fields, relative_path, text
from tools.install_sandbox.host.preparation import (
    digest,
    expected_contents,
    inventory,
    load_json,
    preparation_inputs,
)

_OBSERVATION_FIELDS = (
    "format image_id distribution version entry_point interpreter executable module source_root "
    "resources directories module_owned executable_shebang executable_owned "
    "executable_entry_point executable_regular executable_script errors"
)


def retained_inputs(output: Path) -> tuple[dict[str, object], EffectSpec, SubjectContext]:
    incoming = load_json(output / "inputs.json")
    if not isinstance(incoming, dict):
        raise ValueError("Expected preparation inputs")
    data = cast(dict[str, object], incoming)
    context = SubjectContext.from_data(data.get("context"))
    effects = EffectSpec.from_data(data.get("effects"))
    calculated = preparation_inputs(output / "subject", effects, context)
    if calculated != data:
        raise ValueError("Retained subject or preparation inputs changed")
    expected = expected_contents(output / "subject", data, context)
    if inventory(output / "expected") != {name: digest(value) for name, value in expected.items()}:
        raise ValueError("Retained expected resources changed or are incomplete")
    return data, effects, context


def _encoded(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected base64 encoded resource")
    return value


def _resources(observation: dict[str, object]) -> tuple[dict[str, bytes], set[str]]:
    raw = observation["resources"]
    directories = observation["directories"]
    if not isinstance(raw, dict) or not isinstance(directories, list):
        raise ValueError("Expected complete observed resource inventory")
    files = {
        relative_path(key): base64.b64decode(_encoded(value), validate=True)
        for key, value in cast(dict[str, object], raw).items()
    }
    paths = [relative_path(item) for item in cast(list[object], directories)]
    if len(paths) != len(set(paths)) or set(files) & set(paths):
        raise ValueError("Duplicate observed resource paths")
    return files, set(paths)


def _absolute(value: object) -> str:
    path = text(value)
    parsed = PurePosixPath(path)
    if not parsed.is_absolute() or ".." in parsed.parts or str(parsed) != path:
        raise ValueError("Expected normalized absolute installed binding")
    return path


def _binding(
    inputs: dict[str, object], observed: dict[str, object], image_id: str
) -> dict[str, str]:
    if observed["image_id"] != image_id:
        raise ValueError("Observed image identity differs from host association")
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ValueError("Expected immutable image identifier")
    if any(c not in "0123456789abcdef" for c in image_id[7:]):
        raise ValueError("Invalid immutable image identifier")
    binding = {
        key: text(inputs[key])
        for key in (
            "subject_digest",
            "revision",
            "distribution",
            "version",
            "entry_point",
            "package_root",
        )
    }
    binding.update(
        {
            key: _absolute(observed[key])
            for key in ("interpreter", "executable", "module", "source_root")
        }
    )
    binding["context_digest"] = digest(json.dumps(inputs["context"], sort_keys=True).encode())
    binding["observation_digest"] = digest(json.dumps(observed, sort_keys=True).encode())
    return {"image_id": image_id, **binding}


def _script_diagnostics(inputs: dict[str, object], observed: dict[str, object]) -> list[str]:
    script = base64.b64decode(_encoded(observed["executable_script"]), validate=True)
    diagnostics: list[str] = []
    if not console_wrapper_matches(script, text(inputs["entry_point"])):
        diagnostics.append("Retained executable does not dispatch the declared entry point")
    lines = script.splitlines()
    if not lines or lines[0] != text(observed["executable_shebang"]).encode():
        diagnostics.append("Retained executable shebang differs from its observation")
    return diagnostics


def _identity_diagnostics(inputs: dict[str, object], observed: dict[str, object]) -> list[str]:
    diagnostics = [
        f"Installed {key} differs from captured declaration"
        for key in ("distribution", "version", "entry_point")
        if observed[key] != inputs[key]
    ]
    interpreter = "/opt/install-sandbox/venv/bin/python"
    executable = "/opt/install-sandbox/venv/bin/" + text(inputs["console"])
    for key, expected in (
        ("interpreter", interpreter),
        ("executable", executable),
        ("executable_shebang", "#!" + interpreter),
    ):
        if observed[key] != expected:
            diagnostics.append(f"Installed {key} differs from prepared environment")
    for key in ("executable_owned", "executable_entry_point", "executable_regular"):
        if observed[key] is not True:
            diagnostics.append(f"Installed {key} failed provenance verification")
    module, root = (
        PurePosixPath(text(observed["module"])),
        PurePosixPath(text(observed["source_root"])),
    )
    environment = PurePosixPath("/opt/install-sandbox/venv/lib")
    expected_module = text(inputs["entry_point"]).split(":")[0].split(".")
    module_suffix = "/".join(expected_module[1:])
    suffixes = {module_suffix + ".py", module_suffix + "/__init__.py"}
    if (
        environment not in root.parents
        or root.name != inputs["package_root"]
        or root.parent.name != "site-packages"
        or not root.parent.parent.name.startswith("python3.")
        or root.parent.parent.parent != environment
    ):
        diagnostics.append("Installed resource root is outside the prepared package")
    relative_module = module.relative_to(root).as_posix() if root in module.parents else ""
    if relative_module not in suffixes or observed["module_owned"] is not True:
        diagnostics.append("Imported entry module is not owned by the installed distribution")
    diagnostics.extend(_script_diagnostics(inputs, observed))
    return diagnostics


def _resource_diagnostics(
    output: Path, inputs: dict[str, object], effects: EffectSpec, observed: dict[str, object]
) -> list[str]:
    files, directories = _resources(observed)
    diagnostics: list[str] = []
    for name in cast(list[str], inputs["resources"]):
        if files.get(name) != (output / "expected" / name).read_bytes():
            diagnostics.append(f"Installed resource differs or is missing: {name}")
    expected_dirs = set(cast(list[str], inputs["directories"]))
    if not expected_dirs <= directories:
        diagnostics.append("Installed references directories are incomplete")
    for effect in effects.effects:
        if isinstance(effect, SkillEffect):
            prefix = effect.references + "/"
            expected = {p for p in cast(list[str], inputs["resources"]) if p.startswith(prefix)}
            actual = {p for p in files if p.startswith(prefix)}
            actual_dirs = {p for p in directories if p == effect.references or p.startswith(prefix)}
            if expected != actual or actual_dirs != {
                p for p in expected_dirs if p == effect.references or p.startswith(prefix)
            }:
                diagnostics.append("Installed references inventory differs from captured subject")
    return diagnostics


def _calculate(output: Path, image_id: str) -> PreparationResult:
    runtime = output / "runtime.json"
    if runtime.exists() or runtime.is_symlink():
        failure = fields(load_json(runtime), "state phase detail")
        detail = " ".join(text(failure[key]) for key in ("state", "phase", "detail"))
        return PreparationResult("incomplete", (detail,))
    image = fields(load_json(output / "image.json"), "image_id")
    if image["image_id"] != image_id:
        raise ValueError("Image association differs from retained identity")
    inputs, effects, _context = retained_inputs(output)
    observed = fields(load_json(output / "observation.json"), _OBSERVATION_FIELDS)
    if observed["format"] != "preparation-observation-v1":
        raise ValueError("Unsupported preparation observation")
    errors = observed["errors"]
    if not isinstance(errors, list) or any(
        not isinstance(error, str) for error in cast(list[object], errors)
    ):
        raise ValueError("Expected observation errors")
    if errors:
        return PreparationResult("incomplete", tuple(cast(list[str], errors)))
    binding = _binding(inputs, observed, image_id)
    diagnostics = _identity_diagnostics(inputs, observed)
    diagnostics.extend(_resource_diagnostics(output, inputs, effects, observed))
    return PreparationResult(
        "nonconformant" if diagnostics else "prepared",
        tuple(diagnostics),
        None if diagnostics else binding,
    )


def calculate_preparation(output: Path, image_id: str) -> PreparationResult:
    try:
        return _calculate(output, image_id)
    except (OSError, ValueError, KeyError, TypeError, binascii.Error) as error:
        return PreparationResult("incomplete", (str(error),))


def read_preparation(output: Path) -> PreparationResult:
    """Require the persisted verdict and reproduce every comparison from retained bytes."""
    try:
        saved = fields(load_json(output / "result.json"), "status diagnostics binding")
        image_id = fields(load_json(output / "image.json"), "image_id")["image_id"]
        if not isinstance(image_id, str):
            raise ValueError("Expected retained image identity")
        result = calculate_preparation(output, image_id)
        if result.to_data() != saved:
            raise ValueError("Preparation verdict differs from retained evidence")
        return result
    except (OSError, ValueError, KeyError, TypeError) as error:
        return PreparationResult("incomplete", (str(error),))
