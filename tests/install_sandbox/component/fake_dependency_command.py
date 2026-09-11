#!/usr/bin/env python3
"""Local uv/pip stand-ins: record inputs, never resolve or install anything."""

import json
import os
import signal
import sys
from pathlib import Path

root = Path(os.environ["DEPENDENCY_TEST_ROOT"])
role = Path(sys.argv[0]).name
mode = os.environ.get("DEPENDENCY_TEST_MODE", "success")
arguments = sys.argv[1:]
record: dict[str, object] = {"arguments": arguments, "cwd": os.getcwd()}
if role == "pip-python":
    record["requirements"] = Path(arguments[-1]).read_text()
with (root / "commands.jsonl").open("a") as stream:
    stream.write(json.dumps({"role": role, **record}) + "\n")
if role == "uv":
    if mode == "export_signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if mode == "parent_signal":
        os.kill(os.getppid(), signal.SIGTERM)
        # The preparation program must abort without starting pip.
        import time

        time.sleep(2)
    if mode == "silent_refusal":
        raise SystemExit(1)
    print("complete export diagnostic", file=sys.stderr)
    if mode.startswith("export_exit_"):
        raise SystemExit(int(mode.removeprefix("export_exit_")))
    Path(arguments[arguments.index("--output-file") + 1]).write_text(
        'locked-package==1.2; python_version >= "3.12" \\\n    --hash=sha256:abc123\n'
    )
if role == "pip-python" and mode == "pip_fail":
    raise SystemExit(7)
