"""Capture independent package expectations before building an image."""

import hashlib
import json
import shutil
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.effect_case import SubjectContext, unique_object
from tools.install_sandbox.contracts.effects import EffectSpec, MarkdownSectionEffect, SkillEffect
from tools.install_sandbox.contracts.preparation import PreparationResult
from tools.install_sandbox.contracts.spec import relative_path, text


def load_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular evidence file: {path.name}")
    return cast(
        object, json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Captured subject directory is missing")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Package capture cannot contain symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
        elif not path.is_dir():
            raise ValueError("Package capture contains a special file")
    return result


def package_metadata(subject: Path, context: SubjectContext) -> dict[str, str]:
    project = tomllib.loads((subject / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if not isinstance(project, dict):
        raise ValueError("Expected static project metadata")
    data = cast(dict[str, object], project)
    if data.get("dynamic"):
        raise ValueError("Dynamic package metadata is unsupported")
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        raise ValueError("Expected static graphify console entry")
    console = "graphify"
    entry = cast(dict[str, object], scripts).get(console)
    package_root = relative_path(context.package_root)
    if not console.isidentifier() or ":" not in text(entry):
        raise ValueError("Invalid package console entry")
    return {
        "distribution": text(data.get("name")),
        "version": text(data.get("version")),
        "console": console,
        "entry_point": text(entry),
        "package_root": package_root,
    }


def resource_paths(subject: Path, effects: EffectSpec, package: str) -> tuple[list[str], list[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    root = subject / package
    for effect in effects.effects:
        if isinstance(effect, (SkillEffect, MarkdownSectionEffect)):
            files.add(relative_path(effect.source))
        if isinstance(effect, SkillEffect):
            references = root / relative_path(effect.references)
            if not references.is_dir() or references.is_symlink():
                raise ValueError("Missing references directory")
            directories.add(effect.references)
            for path in references.rglob("*"):
                relative = path.relative_to(root).as_posix()
                (directories if path.is_dir() else files).add(relative)
    for name in files:
        if not (root / name).is_file() or (root / name).is_symlink():
            raise ValueError(f"Missing source resource: {name}")
    return sorted(files), sorted(directories)


def preparation_inputs(
    subject: Path, effects: EffectSpec, context: SubjectContext
) -> dict[str, object]:
    metadata = package_metadata(subject, context)
    files, directories = resource_paths(subject, effects, metadata["package_root"])
    manifest = inventory(subject)
    revision = text(context.revision)
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Expected a full subject revision")
    return {
        "format": "preparation-inputs-v1",
        "context": json.loads(json.dumps(asdict(context))),
        "effects": effects.to_data(),
        **metadata,
        "revision": revision,
        "subject_manifest": manifest,
        "subject_digest": digest(json.dumps(manifest, sort_keys=True).encode()),
        "resources": files,
        "directories": directories,
    }


def expected_contents(
    subject: Path, inputs: dict[str, object], context: SubjectContext
) -> dict[str, bytes]:
    package = subject / text(inputs["package_root"])
    resources = cast(list[str], inputs["resources"])
    if context.version_source in resources:
        raise ValueError("Generated metadata overlaps a source resource")
    expected = {name: (package / name).read_bytes() for name in resources}
    expected[relative_path(context.version_source)] = (
        f"Version: {text(inputs['version'])}\n".encode()
    )
    return expected


def capture_preparation(
    subject: Path, output: Path, effects: EffectSpec, context: SubjectContext
) -> None:
    """Retain the full bounded build subject and independently selected expected bytes."""
    if output.resolve().is_relative_to(subject.resolve()):
        raise ValueError("Preparation evidence must be outside captured subject")
    inputs = preparation_inputs(subject, effects, context)
    expected = expected_contents(subject, inputs, context)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(subject, output / "subject", symlinks=True)
    for name, content in expected.items():
        path = output / "expected" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    write_json(output / "inputs.json", inputs)


def evaluate_preparation(output: Path, image_id: str) -> PreparationResult:
    """Seal a verdict after image-owned observations have been copied out."""
    from tools.install_sandbox.host.preparation_reader import calculate_preparation

    write_json(output / "image.json", {"image_id": image_id})
    result = calculate_preparation(output, image_id)
    write_json(output / "result.json", result.to_data())
    return result
