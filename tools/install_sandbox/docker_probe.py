"""Image-owned isolation probe for the install-sandbox Docker harness."""

from __future__ import annotations

import json
import os
from pathlib import Path

_APP_ROOT = Path("/opt/install-sandbox")
_OUTPUT = Path("/sandbox/output")
_SUBJECT = Path("/sandbox/subject")
_ROOTS = {
    "home": "/sandbox/home",
    "output": "/sandbox/output",
    "prepared_source": "/sandbox/source",
    "project": "/sandbox/project",
    "subject": "/sandbox/subject",
    "working_directory": "/sandbox/work",
    "xdg": "/sandbox/xdg",
}


def main() -> int:
    run_id = _required_environment("INSTALL_SANDBOX_RUN_ID")
    image_id = _required_environment("INSTALL_SANDBOX_IMAGE_ID")
    output_write_succeeded = _check_output_write(run_id)
    checks = {
        "output_write_succeeded": output_write_succeeded,
        "roots_distinct": _roots_are_isolated(),
        "subject_mount_read_only": _mount_is_read_only(_SUBJECT),
        "subject_write_rejected": _subject_write_is_rejected(run_id),
    }
    document: dict[str, object] = {
        "checks": checks,
        "identity": {"gid": os.getgid(), "uid": os.getuid()},
        "image_id": image_id,
        "image_payload": _image_payload(),
        "paths": _ROOTS,
        "run_id": run_id,
        "schema_version": 1,
    }
    _write_attestation(run_id, document)
    return 0 if all(checks.values()) else 2


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _check_output_write(run_id: str) -> bool:
    sentinel = _OUTPUT / f".write-probe-{run_id}"
    try:
        sentinel.write_text("probe", encoding="utf-8")
        sentinel.unlink()
    except OSError:
        return False
    return True


def _roots_are_isolated() -> bool:
    expected_environment = {
        "HOME": _ROOTS["home"],
        "XDG_CONFIG_HOME": _ROOTS["xdg"],
    }
    return (
        len(set(_ROOTS.values())) == len(_ROOTS)
        and all(Path(root).is_dir() for root in _ROOTS.values())
        and all(os.environ.get(name) == value for name, value in expected_environment.items())
        and str(Path.cwd()) == _ROOTS["working_directory"]
    )


def _subject_write_is_rejected(run_id: str) -> bool:
    sentinel = _SUBJECT / f".write-probe-{run_id}"
    try:
        sentinel.write_text("unexpected", encoding="utf-8")
    except OSError:
        return True
    sentinel.unlink(missing_ok=True)
    return False


def _mount_is_read_only(path: Path) -> bool:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(_read_only_mount_line(line, path) for line in lines)


def _read_only_mount_line(line: str, path: Path) -> bool:
    fields = line.split()
    if len(fields) < 7 or fields[4] != str(path) or "-" not in fields:
        return False
    separator = fields.index("-")
    mount_options = fields[5].split(",")
    super_options = fields[separator + 3].split(",") if len(fields) > separator + 3 else []
    return "ro" in mount_options or "ro" in super_options


def _image_payload() -> list[str]:
    return sorted(
        str(path.relative_to(_APP_ROOT)) for path in _APP_ROOT.rglob("*") if path.is_file()
    )


def _write_attestation(run_id: str, document: dict[str, object]) -> None:
    destination = _OUTPUT / "infrastructure-probe.json"
    temporary = _OUTPUT / f".infrastructure-probe-{run_id}.tmp"
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


if __name__ == "__main__":
    raise SystemExit(main())
