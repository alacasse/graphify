#!/usr/bin/env python3
"""Controlled Docker CLI adapter used by install-sandbox Component Evidence."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

_IMAGE_ID = "sha256:" + ("a" * 64)
_ROOTS = {
    "home": "/sandbox/home",
    "output": "/sandbox/output",
    "prepared_source": "/sandbox/source",
    "project": "/sandbox/project",
    "subject": "/sandbox/subject",
    "working_directory": "/sandbox/work",
    "xdg": "/sandbox/xdg",
}


def main(arguments: list[str]) -> int:
    state = Path(os.environ["FAKE_DOCKER_STATE"])
    state.mkdir(parents=True, exist_ok=True)
    _record_command(state, arguments)
    mode = os.environ.get("FAKE_DOCKER_MODE", "success")
    command = arguments[0] if arguments else ""
    if command == "version":
        return _version(mode)
    if command == "build":
        return _build(state, mode, arguments)
    if command == "run":
        return _run(state, mode, arguments)
    if command == "container":
        return _container_list(state, arguments)
    if command == "image":
        return _image(state, mode, arguments)
    if command in {"stop", "kill", "rm"}:
        _resource_marker(state, "container", arguments[-1]).unlink(missing_ok=True)
        return 0
    return 2


def _version(mode: str) -> int:
    if mode == "daemon_fail":
        print("daemon unavailable", file=sys.stderr)
        return 3
    print("29.0.0")
    return 0


def _build(state: Path, mode: str, arguments: list[str]) -> int:
    if mode == "build_timeout":
        time.sleep(60)
    if mode == "build_fail":
        print("build failed", file=sys.stderr)
        return 7
    tag = _option(arguments, "--tag")
    iidfile = Path(_option(arguments, "--iidfile"))
    if mode == "barrier":
        _barrier(state, tag)
    _resource_marker(state, "image", tag).write_text(_IMAGE_ID, encoding="utf-8")
    iidfile.write_text(_IMAGE_ID + "\n", encoding="utf-8")
    if os.environ.get("FAKE_DOCKER_VERBOSE") == "1":
        print("A" * 70_000)
    return 0


def _run(state: Path, mode: str, arguments: list[str]) -> int:
    name = _option(arguments, "--name")
    marker = _resource_marker(state, "container", name)
    marker.write_text("running", encoding="utf-8")
    run_id = _environment(arguments, "INSTALL_SANDBOX_RUN_ID")
    image_id = _environment(arguments, "INSTALL_SANDBOX_IMAGE_ID")
    output = _output_mount(arguments)
    if mode in {"hold", "run_timeout"}:
        (state / f"ready-{run_id}").write_text("ready", encoding="utf-8")
        if mode == "run_timeout":
            _spawn_ignoring_child(state)
        time.sleep(60)
    if mode == "run_fail":
        marker.unlink(missing_ok=True)
        print("run failed", file=sys.stderr)
        return 9
    if mode == "invalid_json":
        (output / "infrastructure-probe.json").write_text("{", encoding="utf-8")
    else:
        _write_attestation(output, run_id, image_id)
    marker.unlink(missing_ok=True)
    return 0


def _write_attestation(output: Path, run_id: str, image_id: str) -> None:
    document: dict[str, object] = {
        "checks": {
            "output_write_succeeded": True,
            "roots_distinct": True,
            "subject_mount_read_only": True,
            "subject_write_rejected": True,
        },
        "identity": {"gid": os.getgid(), "uid": os.getuid()},
        "image_id": image_id,
        "image_payload": ["probe.py"],
        "paths": _ROOTS,
        "run_id": run_id,
        "schema_version": 1,
    }
    path = output / "infrastructure-probe.json"
    path.write_text(json.dumps(document), encoding="utf-8")


def _container_list(state: Path, arguments: list[str]) -> int:
    name_filter = _option(arguments, "--filter")
    name = name_filter.removeprefix("name=^/").removesuffix("$")
    marker = _resource_marker(state, "container", name)
    if marker.exists():
        print("fake-container-id")
    return 0


def _image(state: Path, mode: str, arguments: list[str]) -> int:
    operation = arguments[1] if len(arguments) > 1 else ""
    if operation == "ls":
        reference = _option(arguments, "--filter").removeprefix("reference=")
        if _resource_marker(state, "image", reference).exists():
            print(_IMAGE_ID)
        return 0
    if operation == "rm":
        reference = arguments[-1]
        if mode != "cleanup_fail":
            _resource_marker(state, "image", reference).unlink(missing_ok=True)
        return 0
    return 2


def _spawn_ignoring_child(state: Path) -> None:
    code = (
        "import os, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "open(os.environ['FAKE_DOCKER_CHILD_PID'], 'w').write(str(os.getpid())); "
        "time.sleep(60)"
    )
    environment = dict(os.environ)
    environment["FAKE_DOCKER_CHILD_PID"] = str(state / "child-pid")
    subprocess.Popen([sys.executable, "-c", code], env=environment)
    _wait_for_path(state / "child-pid")


def _barrier(state: Path, tag: str) -> None:
    (state / f"barrier-{_key(tag)}").write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 5
    while len(list(state.glob("barrier-*"))) < 2:
        if time.monotonic() >= deadline:
            raise RuntimeError("fake build barrier timed out")
        time.sleep(0.01)


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _output_mount(arguments: list[str]) -> Path:
    mounts = [arguments[index + 1] for index, item in enumerate(arguments) if item == "--mount"]
    output = next(mount for mount in mounts if "dst=/sandbox/output" in mount)
    source = next(field for field in output.split(",") if field.startswith("src="))
    return Path(source.removeprefix("src="))


def _environment(arguments: list[str], name: str) -> str:
    values = [arguments[index + 1] for index, item in enumerate(arguments) if item == "--env"]
    prefix = name + "="
    return next(value.removeprefix(prefix) for value in values if value.startswith(prefix))


def _option(arguments: list[str], option: str) -> str:
    return arguments[arguments.index(option) + 1]


def _resource_marker(state: Path, resource: str, identity: str) -> Path:
    return state / f"{resource}-{_key(identity)}"


def _key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _record_command(state: Path, arguments: list[str]) -> None:
    identity = f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex}"
    (state / f"command-{identity}.json").write_text(json.dumps(arguments), encoding="utf-8")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    raise SystemExit(main(sys.argv[1:]))
