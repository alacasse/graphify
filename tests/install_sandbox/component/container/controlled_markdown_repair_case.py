"""Inject intermediate filesystem failures while retaining the actual runner and verifier."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tools.install_sandbox.container.__main__ import main
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner


def run() -> int:
    subject, case, output = sys.argv[1:]
    work = Path(output).parents[2] / "work" / Path(output).name
    document = work / "environment/project/.sandbox-reference/instructions.md"
    mode = os.environ.get("CONTROLLED_MARKDOWN_PREPARATION", "passed")
    preparing = (Path(output) / "steps/1/preparation/plan.json").exists
    write_bytes, read_bytes = Path.write_bytes, Path.read_bytes

    def write(path: Path, content: bytes) -> int:
        if preparing() and path == document:
            content = _alter(mode, path, content, work)
        return write_bytes(path, content)

    def read(path: Path) -> bytes:
        if preparing() and path == document and mode == "unreadable":
            raise PermissionError("Controlled Markdown observation denied")
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
            stream.write(b"Partial Markdown write\n")
        raise OSError("Controlled Markdown preparation write failed")
    if mode == "no_change":
        return path.read_bytes()
    if mode == "wrong_content":
        return b"Incorrect shared document\n"
    if mode == "lost_suffix":
        return content.split(b"## Changes")[0]
    if mode == "extra_change":
        (work / "environment/home/personal-notes.txt").write_text("Changed home\n")
    return content


if __name__ == "__main__":
    raise SystemExit(run())
