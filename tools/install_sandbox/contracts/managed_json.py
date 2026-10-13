"""Independent managed JSON facts derived only from case inputs."""

import hashlib
from dataclasses import asdict
from pathlib import PurePosixPath

from tools.install_sandbox.contracts.case import InstallTestCase, destinations


def sidecars(case: InstallTestCase) -> dict[str, str]:
    target = destinations(case)["json"]
    return {
        "state": target + ".graphify-state.json",
        "lock": target + ".graphify.lock",
        "journal": target + ".graphify-journal.json",
    }


def registry(case: InstallTestCase) -> dict[str, object]:
    return {
        "version": 1,
        "owner": "graphify",
        "target": PurePosixPath(destinations(case)["json"]).name,
        "effects": [asdict(hook) for hook in case.spec.json_hooks],
    }


def resolution(case: InstallTestCase) -> dict[str, object]:
    target = destinations(case)["json"]
    witness = next(
        file["content"]
        for file in case.initial_files
        if file["root"] == "project" and file["path"] == target
    )
    return {
        "version": 1,
        "target": target,
        "snapshot_sha256": hashlib.sha256(witness.encode("utf-8")).hexdigest(),
        "registry_absent": True,
        "effects": [{"id": hook.id, "action": "create"} for hook in case.spec.json_hooks],
    }


def needs_resolution(case: InstallTestCase) -> bool:
    return case.name in {"first-install", "reinstall"}


def is_transaction_temporary(case: InstallTestCase, path: str) -> bool:
    """Select possible transaction leftovers for retention, never grant ownership."""
    destinations_to_retain = [destinations(case)["json"], *sidecars(case).values()]
    return any(path.startswith(target + ".graphify-tmp-") for target in destinations_to_retain)
