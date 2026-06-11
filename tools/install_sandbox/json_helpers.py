from __future__ import annotations

from typing import cast


def object_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def object_dicts(value: object) -> list[dict[str, object]]:
    return [object_dict(item) for item in object_list(value) if isinstance(item, dict)]
