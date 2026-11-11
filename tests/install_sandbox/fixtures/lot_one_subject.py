"""Literal installer: deliberately independent of sandbox declarations and mutation code."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    print(json.dumps({"fixture_invocation": sys.argv[1:]}), flush=True)
    scope = sys.argv[sys.argv.index("--scope") + 1]
    home = Path(os.environ["HOME"])
    destinations = (
        [Path.cwd() / ".birch/editor.json", home / ".birch/assistant.json"]
        if scope == "project"
        else [home / ".birch/user.json"]
    )
    fault = Path(__file__).with_name("fault.txt").read_text().strip()
    for destination in destinations:
        backup = destination.with_name(destination.name + ".graphify-bak")
        if destination.exists() and not backup.exists():
            backup.write_bytes(destination.read_bytes())
        data = json.loads(destination.read_text()) if destination.exists() else {}
        hooks = data.setdefault("hooks", {})
        entries = hooks.setdefault("SessionStart", [])
        command = {"type": "command", "command": "birch run", "timeout": 10}
        broken = (
            fault == scope or fault == "second-project" and destination.name == "assistant.json"
        )
        matching = [entry for entry in entries if entry.get("matcher") == "*"]
        occurrences = [
            (entry, index)
            for entry in matching
            for index, member in enumerate(entry.get("hooks", []))
            if member == command
        ]
        if not (broken and len(occurrences) > 1):
            survivor = occurrences[0] if occurrences else None
            for entry in matching:
                entry["hooks"] = [
                    member
                    for index, member in enumerate(entry.get("hooks", []))
                    if member.get("command") != "birch run"
                    or survivor is not None
                    and entry is survivor[0]
                    and index == survivor[1]
                ]
            if survivor is None:
                if matching:
                    if fault == "permuted":
                        matching[0]["hooks"].insert(0, command)
                    else:
                        matching[0]["hooks"].append(command)
                else:
                    entries.append({"matcher": "*", "hooks": [command]})
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data) + "\n")
    return 0
