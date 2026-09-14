"""Inject JSON preparation I/O faults around the real runner and verifier."""

import json
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
    document = work / "environment/project/.sandbox-reference/settings.json"
    mode = os.environ.get("CONTROLLED_JSON_PREPARATION", "passed")
    preparing = (Path(output) / "steps/1/preparation/plan.json").exists
    write_bytes, read_bytes = Path.write_bytes, Path.read_bytes
    written = False

    def write(path: Path, content: bytes) -> int:
        nonlocal written
        if preparing() and path == document:
            content = _alter(mode, path, content, work)
            written = True
        return write_bytes(path, content)

    def read(path: Path) -> bytes:
        if (
            preparing()
            and path == document
            and (mode == "read_failure" or (written and mode == "unreadable"))
        ):
            raise PermissionError("Controlled JSON read denied")
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
            stream.write(b'{"theme":')
        raise OSError("Controlled JSON preparation write failed")
    if mode == "no_change":
        return path.read_bytes()
    if mode == "invalid":
        return b"Invalid JSON\n"
    if mode == "extra_change":
        (work / "environment/home/personal-notes.txt").write_text("Changed home\n")
    return _json_change(mode, content)


def _json_change(mode: str, content: bytes) -> bytes:
    data = json.loads(content)
    if mode == "wrong_entry":
        data["instructions"] = ["team-guidelines.md", "skills/graphify/SKILL.md"]
    if mode == "reverse":
        data["instructions"].reverse()
    if mode == "theme":
        data["theme"] = "light"
    if mode == "hooks":
        data["hooks"] = {}
    if mode == "hook_extra":
        data["hooks"]["PreToolUse"][0]["hooks"][0]["extra"] = True
    if mode == "format":
        return json.dumps(data, sort_keys=True, indent=4).encode()
    return json.dumps(data).encode()


if __name__ == "__main__":
    raise SystemExit(run())
