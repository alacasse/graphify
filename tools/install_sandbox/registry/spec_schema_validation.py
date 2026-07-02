from __future__ import annotations

from typing import AbstractSet, Mapping


class SpecSchemaValidationError(ValueError):
    pass


def reject_unknown_fields(data: Mapping[str, object], allowed: AbstractSet[str], context: str) -> None:
    unknown = sorted(str(key) for key in data if key not in allowed)
    if not unknown:
        return
    if len(unknown) == 1:
        raise SpecSchemaValidationError(f"{context}: unknown field: {unknown[0]}")
    raise SpecSchemaValidationError(f"{context}: unknown fields: {', '.join(unknown)}")
