"""Verify a ZIP against raw evidence before permitting its removal."""

import json
import stat
import zipfile
from pathlib import Path
from typing import cast

from tools.install_sandbox.host.docker_runtime import SignalCapture
from tools.install_sandbox.host.output_report import atomic_text, relative_values

_BLOCK = 1024 * 1024


def check_interrupt(interrupts: SignalCapture) -> None:
    if interrupts.signal_number is not None:
        raise InterruptedError(f"Interrupted by signal {interrupts.signal_number}")


def export_summary(evidence: Path) -> None:
    """Only the exported campaign summary needs host path rebasing."""
    machine = evidence / "campaign.json"
    if machine.exists():
        payload = cast(dict[str, object], json.loads(machine.read_text()))
        atomic_text(machine, json.dumps(relative_values(payload, evidence, "."), indent=2) + "\n")
    human = evidence / "campaign.txt"
    if human.exists():
        atomic_text(human, human.read_text().replace(str(evidence), "."))


def archive_evidence(directory: Path, interrupts: SignalCapture) -> None:
    evidence = directory / "evidence"
    check_interrupt(interrupts)
    export_summary(evidence)
    inventory = _inventory(evidence)
    temporary = directory / "evidence.zip.tmp"
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in inventory:
            _archive_entry(archive, path, directory, interrupts)
    _verify_archive(temporary, inventory, directory, interrupts)
    check_interrupt(interrupts)
    temporary.replace(directory / "evidence.zip")


def _inventory(evidence: Path) -> list[Path]:
    paths = [evidence, *sorted(evidence.rglob("*"))]
    for path in paths:
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"Cannot archive a symlink or special evidence entry: {path}")
    return paths


def _archive_entry(
    archive: zipfile.ZipFile, path: Path, root: Path, interrupts: SignalCapture
) -> None:
    check_interrupt(interrupts)
    name = path.relative_to(root).as_posix()
    if path.is_dir():
        archive.writestr(name + "/", b"")
        return
    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as destination:
        while block := source.read(_BLOCK):
            check_interrupt(interrupts)
            destination.write(block)


def _verify_archive(
    temporary: Path, paths: list[Path], root: Path, interrupts: SignalCapture
) -> None:
    with zipfile.ZipFile(temporary) as archive:
        expected = [p.relative_to(root).as_posix() + ("/" if p.is_dir() else "") for p in paths]
        if archive.namelist() != expected or _inventory(root / "evidence") != paths:
            raise ValueError("Archive inventory differs from raw evidence")
        for path, name in zip(paths, expected, strict=True):
            check_interrupt(interrupts)
            if not path.is_dir():
                _compare_entry(archive, name, path, interrupts)


def _compare_entry(
    archive: zipfile.ZipFile, name: str, path: Path, interrupts: SignalCapture
) -> None:
    with archive.open(name) as archived, path.open("rb") as original:
        while True:
            check_interrupt(interrupts)
            block = original.read(_BLOCK)
            if archived.read(_BLOCK) != block:
                raise ValueError(f"Archive bytes differ: {name}")
            if not block:
                break
