"""Literal installer: deliberately independent of sandbox declarations and mutation code."""

import json
import os
import sys
from pathlib import Path


def install_hook(entries, matcher, command, *, broken=False, prepend=False, move_after=False):
    """Keep one exact hook in its original group and preserve personal members."""
    matching = [entry for entry in entries if entry.get("matcher") == matcher]
    occurrences = [
        (entry, index)
        for entry in matching
        for index, member in enumerate(entry.get("hooks", []))
        if member == command
    ]
    if broken and len(occurrences) > 1:
        return
    survivor = occurrences[0] if occurrences else None
    for entry in matching:
        entry["hooks"] = [
            member
            for index, member in enumerate(entry.get("hooks", []))
            if member.get("command") != command["command"]
            or (survivor is not None and entry is survivor[0] and index == survivor[1])
        ]
    if survivor is None:
        if matching:
            matching[0]["hooks"].append(command)
        else:
            group = {"matcher": matcher, "hooks": [command]}
            if prepend:
                entries.insert(0, group)
            else:
                entries.append(group)
    if move_after:
        # Move an existing seeded target after its personal neighbor.
        for entry in matching:
            members = entry["hooks"]
            entry["hooks"] = [m for m in members if m != command] + [
                m for m in members if m == command
            ]


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
        broken = fault == scope or (
            fault == "second-project" and destination.name == "assistant.json"
        )
        has_layout = fault in ("layout", "permuted") and destination.name == "assistant.json"
        install_hook(
            entries, "*", command, broken=broken, move_after=has_layout and fault == "permuted"
        )
        if has_layout:
            # An existing seeded layout group stays in place with its witnesses.
            install_hook(
                entries,
                "FixtureLayout",
                {"type": "command", "command": "birch layout", "timeout": 10},
                prepend=fault == "permuted",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data) + "\n")
    return 0
