from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def artifact_relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def compact_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    replacements = {
        "/tmp/graphify-project/": "project/",
        "/tmp/graphify-home/": "home/",
        "/tmp/graphify-user-cwd/": "user_cwd/",
    }
    for prefix, replacement in replacements.items():
        if value.startswith(prefix):
            return replacement + value[len(prefix) :]
    return value


def read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_error": f"invalid json: {exc}"}
    return data if isinstance(data, dict) else {"_error": "json root is not an object"}


def file_text_snippet(path: Path, limit: int = 500) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def normalized_text_snippet(value: Any, *, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def tail_file(path: Path, *, limit: int = 600) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]
