#!/usr/bin/env python3
"""Controlled Docker CLI adapter used by install-sandbox Component Evidence."""

from __future__ import annotations

import base64
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
    if command in {"info", "version"}:
        return _identity(mode, command)
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


def _identity(mode: str, command: str) -> int:
    if command == "info":
        if mode == "daemon_fail":
            return 3
        print(os.environ.get("FAKE_DOCKER_DAEMON_ID", "controlled-daemon"))
        return 0
    return _version(mode)


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
    _dependency_evidence(state, mode)
    context = Path(arguments[-1])
    shutil.copytree(context / "subject", state / "reference", dirs_exist_ok=True)
    shutil.copytree(context / "verified", state / "verified", dirs_exist_ok=True)
    (state / "captured-context.json").write_text(
        json.dumps(sorted(p.name for p in context.iterdir()))
    )
    if os.environ.get("CONTROLLED_INSTALLER"):
        shutil.copyfile(os.environ["CONTROLLED_INSTALLER"], state / "graphify")
        (state / "graphify").chmod(0o755)
    if mode != "cached":
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
    if any(value.endswith("/verify_preparation.py") for value in arguments):
        _retrieve_dependency_evidence(state, arguments)
        _verified_observation(state, arguments)
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


def _verified_observation(state: Path, arguments: list[str]) -> None:
    if not (state / "verified/preparation/inputs.json").is_file():
        return
    payload = _package_observation(state)
    fault = os.environ.get("FAKE_DOCKER_PREPARATION_FAULT")
    if fault == "missing-observation":
        return
    if fault in {"version", "image_id"}:
        payload[fault] = "wrong-version" if fault == "version" else "sha256:" + "f" * 64
    if fault == "resource":
        payload["resources"] = {}
    for argument in arguments:
        if argument.startswith("type=bind,") and ",dst=/sandbox/preparation" in argument:
            output = Path(argument.split("src=", 1)[1].split(",", 1)[0])
            (output / "observation.json").write_text(json.dumps(payload))


def _package_observation(state: Path) -> dict[str, object]:
    package = state / "reference/graphify"
    resources = {
        p.relative_to(package).as_posix(): base64.b64encode(p.read_bytes()).decode()
        for p in package.rglob("*")
        if p.is_file()
    }
    return {
        "format": "preparation-observation-v1",
        "image_id": _IMAGE_ID,
        "distribution": "graphifyy",
        "version": "1.2.3",
        "entry_point": "graphify.cli:main",
        "interpreter": "/opt/install-sandbox/venv/bin/python",
        "executable": "/opt/install-sandbox/venv/bin/graphify",
        "module": "/opt/install-sandbox/venv/lib/python3.12/site-packages/graphify/cli.py",
        "source_root": "/opt/install-sandbox/venv/lib/python3.12/site-packages/graphify",
        "resources": resources,
        "directories": [
            p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_dir()
        ],
        "executable_script": base64.b64encode(
            b"#!/opt/install-sandbox/venv/bin/python\nimport re\nimport sys\n"
            b"from graphify.cli import main\nif __name__ == '__main__':\n"
            b"    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
            b"    sys.exit(main())\n"
        ).decode(),
        "executable_owned": True,
        "executable_entry_point": True,
        "executable_regular": True,
        "module_owned": True,
        "executable_shebang": "#!/opt/install-sandbox/venv/bin/python",
        "errors": [],
    }


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
    if os.environ.get("FAKE_DOCKER_DISCARD_WORK") == "1":
        shutil.rmtree(_output_mount(arguments).parents[2] / "work", ignore_errors=True)
    if mode != "container_cleanup_fail":
        marker.unlink(missing_ok=True)
    return 9 if mode == "run_fail" else code


def _retrieve_dependency_evidence(state: Path, arguments: list[str]) -> None:
    mounts = [arguments[i + 1] for i, item in enumerate(arguments) if item == "--mount"]
    mount = next(value for value in mounts if "dst=/sandbox/preparation" in value)
    source = next(field[4:] for field in mount.split(",") if field.startswith("src="))
    shutil.copytree(state / "dependency-layer", Path(source), dirs_exist_ok=True)


def _dependency_evidence(state: Path, build_mode: str) -> None:
    output = state / "dependency-layer"
    if build_mode == "cached" and output.exists():
        return
    output.mkdir(exist_ok=True)
    mode = os.environ.get("FAKE_DEPENDENCIES", "locked")
    if mode == "missing":
        return
    value = {"mode": mode, "warning": None, "diagnostic": None}
    if mode in {"resolved", "missing_diagnostic"}:
        value.update(
            mode="resolved", warning="Lock not validated offline", diagnostic="dependencies.log"
        )
        if mode == "resolved":
            (output / "dependencies.log").write_text("Full retained uv diagnostic\n")
    (output / "dependencies.json").write_text(json.dumps(value))


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
            str(state / "verified/expected")
            if _option(arguments, "--reference-sources") == "/opt/install-sandbox/expected"
            else str(state / "reference"),
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
