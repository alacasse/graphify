"""Local process adapter with controlled filesystem failures during preparation."""

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
    result_directory = Path(output)
    work = result_directory.parents[2] / "work" / result_directory.name
    project = work / "environment/project"
    refs = project / ".sandbox-reference/skills/graphify/references"
    mode = os.environ.get("CONTROLLED_REPAIR_PREPARATION", "passed")
    return _execute(subject, case, output, work, refs, mode)


def _execute(subject: str, case: str, output: str, work: Path, refs: Path, mode: str) -> int:
    result_directory = Path(output)
    write_bytes, read_bytes = Path.write_bytes, Path.read_bytes

    preparing = (result_directory / "steps/1/preparation/plan.json").exists

    def write(path: Path, content: bytes) -> int:
        if preparing() and path == refs / "sub/two.md":
            content = _alter_write(mode, path, content, work, refs)
        return write_bytes(path, content)

    def read(path: Path) -> bytes:
        if preparing() and path == refs / "sub/two.md" and mode == "unreadable":
            raise PermissionError("Controlled preparation observation denied")
        return read_bytes(path)

    original_unlink = Path.unlink

    def remove(path: Path, missing_ok: bool = False) -> None:
        if preparing() and path == refs / "one.md":
            _check_delete(mode)
            if mode == "no_delete":
                return
        original_unlink(path, missing_ok=missing_ok)

    with (
        patch.object(Path, "write_bytes", write),
        patch.object(Path, "read_bytes", read),
        patch.object(Path, "unlink", remove),
    ):
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


def _check_delete(mode: str) -> None:
    if mode == "delete_failure":
        raise OSError("Controlled preparation deletion failed")


def _alter_write(mode: str, path: Path, content: bytes, work: Path, refs: Path) -> bytes:
    if mode == "write_failure":
        with path.open("wb") as stream:
            stream.write(b"Partial preparation write\n")
        raise OSError("Controlled preparation write failed")
    if mode == "wrong_content":
        return b"Wrong preparation content\n"
    if mode == "extra_change":
        (work / "environment/home/personal-notes.txt").write_bytes(b"Changed home\n")
    if mode == "extra_reference":
        (refs / "extra.md").write_bytes(b"Unexpected preparation file\n")
    return content


if __name__ == "__main__":
    raise SystemExit(run())
