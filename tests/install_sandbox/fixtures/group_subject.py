"""Independent literal product for group acceptance; never imports sandbox code."""

import json
import os
import shutil
import signal
import sys
from pathlib import Path


def paths():
    home, project = Path(os.environ["HOME"]), Path.cwd()
    return {
        "cedar:user": home / ".cedar/user.json",
        "cedar:project": project / ".cedar/project.json",
        "birch:project": project / ".birch/hooks.json",
    }


def oracle():
    # This output is captured before container cleanup, independently of the walker.
    disk = {}
    for participant, path in paths().items():
        try:
            disk[participant] = path.read_text()
        except OSError as error:
            disk[participant] = {"error": error.errno}
        backup = path.with_name(path.name + ".graphify-bak")
        try:
            disk[participant + ":backup"] = backup.read_text()
        except OSError as error:
            disk[participant + ":backup"] = {"error": error.errno}
    receipt = Path.cwd() / ".cedar/receipt.txt"
    disk["cedar:receipt"] = receipt.read_text() if receipt.exists() else None
    print(json.dumps({"disk_oracle": disk}), flush=True)


def main():
    argv = sys.argv[1:]
    print(json.dumps({"fixture_invocation": argv}), flush=True)
    fault = Path(__file__).with_name("fault.txt").read_text().strip()
    if argv[0] == "install":
        participant = argv[1]
        destination = paths()[participant]
        if fault == "wrong-root" and participant == "cedar:project":
            destination = Path(os.environ["HOME"]) / ".cedar/project.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        commands = (
            ["birch first", "birch second"] if participant == "birch:project" else ["cedar run"]
        )
        backup = destination.with_name(destination.name + ".graphify-bak")
        if destination.exists() and not backup.exists():
            backup.write_bytes(destination.read_bytes())
        document = (
            json.loads(destination.read_text()) if destination.exists() else {"owner": "personal"}
        )
        groups = document.setdefault("hooks", {}).setdefault("SessionStart", [])
        group = next((entry for entry in groups if entry.get("matcher") == "*"), None)
        if group is None:
            group = {"matcher": "*", "hooks": []}
            groups.append(group)
        for command in commands:
            group["hooks"][:] = [
                member for member in group["hooks"] if member.get("command") != command
            ]
            group["hooks"].append({"type": "command", "command": command, "timeout": 10})
        destination.write_text(json.dumps(document) + "\n")
        if participant == "cedar:project":
            (Path.cwd() / ".cedar/receipt.txt").write_text("cedar installed\n")
        if fault == "wrong-backup" and participant == "cedar:project":
            backup.write_text("corrupt backup\n")
        if fault == "forbidden-registry" and participant == "cedar:project":
            destination.with_name(destination.name + ".graphify-state.json").write_text("{}")
        if fault == "missing-home" and participant == "cedar:project":
            shutil.rmtree(Path(os.environ["HOME"]))
        oracle()
        return 0
    for participant in argv[1:]:
        destination = paths()[participant]
        document = json.loads(destination.read_text())
        members = document["hooks"]["SessionStart"][0]["hooks"]
        managed = "birch " if participant.startswith("birch:") else "cedar "
        if participant == "birch:project" and fault == "partial-signal":
            members[:] = [member for member in members if member["command"] != "birch first"]
        else:
            members[:] = [member for member in members if not member["command"].startswith(managed)]
        if not members:
            document["hooks"].pop("SessionStart")
        if fault == "lost-personal":
            document["hooks"].pop("PreToolUse", None)
        destination.write_text(json.dumps(document) + "\n")
        if fault == "reformat-protected":
            protected = paths()["cedar:user"]
            protected.write_text(json.dumps(json.loads(protected.read_text()), indent=4))
        if fault == "unreadable-home":
            protected = paths()["cedar:user"]
            protected.chmod(0)
        if fault == "omitted-home" and Path(os.environ["HOME"]).exists():
            shutil.rmtree(Path(os.environ["HOME"]))
        if participant == "cedar:project":
            (Path.cwd() / ".cedar/receipt.txt").unlink()
        oracle()
        if fault in ("partial-signal", "between-signal"):
            os.kill(os.getpid(), signal.SIGTERM)
    return 0
