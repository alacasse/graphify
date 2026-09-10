"""Controlled filesystem failures during backup preparation; keep the real verifier."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.install_sandbox.container_main import main
from tools.install_sandbox.driver import InstallerDriver
from tools.install_sandbox.runner import InstallTestRunner


def run() -> int:
    subject, case, output = sys.argv[1:]
    work = Path(output).parents[2] / "work" / Path(output).name
    skill = work / "environment/project/.sandbox-reference/skills/graphify/SKILL.md"
    backup = Path(str(skill) + ".bak")
    mode = os.environ.get("CONTROLLED_BACKUP_PREPARATION", "passed")
    preparing = (Path(output) / "steps/1/preparation/plan.json").exists
    write_bytes, read_bytes = Path.write_bytes, Path.read_bytes

    def write(path: Path, content: bytes) -> int:
        if preparing() and path == backup:
            if mode == "no_write":
                return len(content)
            if mode == "write_denied":
                raise PermissionError("Controlled backup write denied")
            content = _alter(mode, path, content, work)
        return write_bytes(path, content)

    def read(path: Path) -> bytes:
        if preparing() and path == backup and mode == "unreadable":
            raise PermissionError("Controlled backup observation denied")
        if (
            path == backup
            and mode == "final_unreadable"
            and (Path(output) / "steps/1/stdout.txt").exists()
        ):
            raise PermissionError("Controlled backup observation denied")
        return read_bytes(path)

    with patch.object(Path, "write_bytes", write), patch.object(Path, "read_bytes", read):
        return main(
            [
                "--reference-sources",
                subject,
                "--prepared-executable",
                os.environ["CONTROLLED_INSTALLER"],
                "--case-file",
                case,
                "--output-directory",
                output,
                "--work-directory",
                str(work),
            ],
            runner=InstallTestRunner(InstallerDriver(timeout=0.3)),
        )


def _alter(mode: str, path: Path, content: bytes, work: Path) -> bytes:
    if mode == "write_failure":
        with path.open("wb") as stream:
            stream.write(b"Partial backup write\n")
        raise OSError("Controlled backup preparation write failed")
    if mode == "wrong_content":
        return b"Wrong backup witness\n"
    if mode == "source_only":
        return b"# Local skill\n"
    if mode == "extra_change":
        (work / "environment/home/personal-notes.txt").write_text("Changed home\n")
    if mode == "skill_changed":
        path.with_suffix("").write_text("Changed skill\n")
    return content


if __name__ == "__main__":
    raise SystemExit(run())
