#!/usr/bin/env python3
"""Controlled Docker CLI adapter used by install-sandbox Component Evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

_IMAGE_ID = "sha256:" + ("a" * 64)


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
        if mode in {"container_cleanup_fail", "verify_cleanup_fail"}:
            print("container cleanup refused", file=sys.stderr)
            return 8
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
    if os.environ.get("CONTROLLED_PREPARATION_FAIL") == "1":
        print("controlled package preparation failed", file=sys.stderr)
        return 9
    context = Path(arguments[-1])
    shutil.copytree(context / "subject", state / "reference", dirs_exist_ok=True)
    (state / "captured-context.json").write_text(
        json.dumps(sorted(p.name for p in context.iterdir()))
    )
    if os.environ.get("CONTROLLED_INSTALLER"):
        shutil.copyfile(os.environ["CONTROLLED_INSTALLER"], state / "graphify")
        (state / "graphify").chmod(0o755)
    print("controlled package preparation", flush=True)
    tag = _option(arguments, "--tag")
    iidfile = Path(_option(arguments, "--iidfile"))
    _resource_marker(state, "image", tag).write_text(_IMAGE_ID, encoding="utf-8")
    if mode != "missing_image_id":
        image_id = "invalid" if mode == "invalid_image_id" else _IMAGE_ID
        iidfile.write_text(image_id + "\n", encoding="utf-8")
    if os.environ.get("FAKE_DOCKER_VERBOSE") == "1":
        print("A" * 70_000)
    return 0


def _run(state: Path, mode: str, arguments: list[str]) -> int:
    name = _option(arguments, "--name")
    marker = _resource_marker(state, "container", name)
    marker.write_text("running", encoding="utf-8")
    if "--help" in arguments:
        return _verify(mode, marker)
    run_id = _environment(arguments, "INSTALL_SANDBOX_RUN_ID")
    output = _output_mount(arguments)
    if os.environ.get("FAKE_DOCKER_CASE_PROGRAM"):
        return _case_program(state, mode, arguments, marker)
    (output / "journal.log").write_text("controlled container evidence\n", encoding="utf-8")
    print("container started", flush=True)
    _hold(state, mode, run_id)
    if mode == "run_fail":
        marker.unlink(missing_ok=True)
        print("run failed", file=sys.stderr)
        return 9
    if mode == "invalid_result":
        (output / "result.json").write_text("{", encoding="utf-8")
    if mode != "container_cleanup_fail":
        marker.unlink(missing_ok=True)
    return 0


def _hold(state: Path, mode: str, run_id: str) -> None:
    if mode == "run_interrupt":
        os.kill(os.getppid(), signal.SIGTERM)
        time.sleep(60)
    if mode in {"hold", "run_timeout"}:
        (state / f"ready-{run_id}").write_text("ready", encoding="utf-8")
        if mode == "run_timeout":
            _spawn_ignoring_child(state)
        time.sleep(60)


def _case_program(state: Path, mode: str, arguments: list[str], marker: Path) -> int:
    code = _execute_case(state, arguments)
    if mode != "container_cleanup_fail":
        marker.unlink(missing_ok=True)
    return 9 if mode == "run_fail" else code


def _verify(mode: str, marker: Path) -> int:
    if mode == "verify_interrupt":
        os.kill(os.getppid(), signal.SIGTERM)
        time.sleep(60)
    if mode == "verify_timeout":
        time.sleep(60)
    if mode != "verify_cleanup_fail":
        marker.unlink(missing_ok=True)
    print("controlled graphify help", flush=True)
    return 8 if mode == "verify_fail" else 0


def _execute_case(state: Path, arguments: list[str]) -> int:
    mounts: dict[str, str] = {}
    for index, argument in enumerate(arguments):
        if argument == "--mount":
            parts = dict(
                item.split("=", 1) for item in arguments[index + 1].split(",") if "=" in item
            )
            mounts[parts["dst"]] = parts["src"]
    return subprocess.call(
        [
            sys.executable,
            os.environ["FAKE_DOCKER_CASE_PROGRAM"],
            str(state / "reference"),
            mounts["/sandbox/case.json"],
            mounts["/sandbox/output"],
        ],
        env={**os.environ, "CONTROLLED_INSTALLER": str(state / "graphify")},
    )


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
