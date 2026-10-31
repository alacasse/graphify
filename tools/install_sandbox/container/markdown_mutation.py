"""Apply bound Markdown mutations and capture their physical result."""

import hashlib
import os

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


def apply_markdown_mutation(
    operation: BoundMarkdownMutation,
    environment: EffectEnvironment,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
) -> None:
    preparation = environment.case.intermediate_preparation
    if preparation is None or preparation.destination != operation.destination:
        raise ValueError("Operation destination differs from case")
    retained = operation.verify_binding(case_bytes, first_after)
    root = environment.project if operation.destination.root == "project" else environment.home
    path = root / operation.destination.path
    if path.resolve() != path or not path.is_file():
        raise ValueError("Operation requires original regular document")
    with os.fdopen(os.open(path, os.O_RDWR | os.O_NOFOLLOW), "r+b") as stream:
        current = stream.read()
        if current != retained:
            raise ValueError("Document changed since validated observation")
        stream.seek(0)
        stream.write(current[: operation.start] + operation.replacement + current[operation.end :])
        stream.truncate()


def capture_performed_mutation(
    operation: BoundMarkdownMutation, environment: EffectEnvironment
) -> PerformedMutation:
    root = environment.project if operation.destination.root == "project" else environment.home
    path = root / operation.destination.path
    if path.resolve() != path or not path.is_file():
        raise ValueError("Performed mutation requires a regular document")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        return PerformedMutation(operation, hashlib.sha256(stream.read()).hexdigest())
