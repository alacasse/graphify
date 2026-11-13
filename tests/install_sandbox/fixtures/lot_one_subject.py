"""Literal installer: deliberately independent of sandbox declarations and mutation code."""

import json
import os
import sys
from pathlib import Path


def install_hook(entries, matcher, command, *, broken=False, prepend=False, move_after=False):
    """Install an absent exact hook; optionally relocate it beside its seeded group."""
    matching = [entry for entry in entries if entry.get("matcher") == matcher]
    source = next((entry for entry in matching if command in entry.get("hooks", [])), None)
    if source is None:
        if broken:
            return
        if matching:
            source = matching[0]
            source["hooks"].append(command)
        else:
            source = {"matcher": matcher, "hooks": [command]}
            if prepend:
                entries.insert(0, source)
            else:
                entries.append(source)
    if move_after and any(member != command for member in source["hooks"]):
        # Keep personal neighbors in place and relocate only the managed member.
        source["hooks"].remove(command)
        destination = next((entry for entry in matching if not entry["hooks"]), None)
        if destination is None:
            entries.append({"matcher": matcher, "hooks": [command]})
        else:
            destination["hooks"].append(command)


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
        original = json.loads(backup.read_text()) if backup.exists() else {}
        original_commands = {
            member.get("command")
            for groups in original.get("hooks", {}).values()
            for group in groups
            for member in group.get("hooks", [])
        }
        has_layout = destination.name in ("assistant.json", "moved-assistant.json")
        install_hook(
            entries,
            "*",
            command,
            broken=broken and scope == "user" and "birch run" in original_commands,
            move_after=has_layout and fault == "permuted",
        )
        if has_layout:
            # An existing seeded layout group stays in place with its witnesses.
            install_hook(
                entries,
                "FixtureLayout",
                {"type": "command", "command": "birch layout", "timeout": 10},
                prepend=fault == "permuted",
                broken=broken and scope == "project" and "birch layout" in original_commands,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data) + "\n")
    return 0
