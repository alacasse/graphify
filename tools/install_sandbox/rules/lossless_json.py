"""Lossless JSON values for retained settings, including arbitrary decimal precision."""

import json
from decimal import Decimal, InvalidOperation
from typing import cast


class _NegativeIntegerZero(int):
    """Retain the sign of JSON integer -0 without treating it as a decimal."""


def _integer(token: str) -> int:
    value = int(token)
    return _NegativeIntegerZero(value) if token == "-0" else value


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError(f"Invalid JSON constant: {value}")


def _decimal(token: str) -> Decimal:
    try:
        return Decimal(token)
    except InvalidOperation as exc:
        raise ValueError("JSON decimal exceeds supported range") from exc


def decode_json(content: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(
            content.decode("utf-8"),
            parse_float=_decimal,
            parse_int=_integer,
            object_pairs_hook=_object,
            parse_constant=_constant,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds parser depth") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return cast(dict[str, object], value)


def _scalar(value: object) -> str:
    if isinstance(value, _NegativeIntegerZero):
        return "-0"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Invalid JSON decimal")
        token = str(value)
        return token if any(c in token for c in ".eE") else token + ".0"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def _container_tokens(value: object) -> list[tuple[bool, object]]:
    if isinstance(value, dict):
        tokens: list[tuple[bool, object]] = [(True, "{")]
        for key, item in cast(dict[str, object], value).items():
            if len(tokens) > 1:
                tokens.append((True, ","))
            tokens.extend(((True, json.dumps(key) + ":"), (False, item)))
        return [*tokens, (True, "}")]
    tokens = [(True, "[")]
    for item in cast(list[object], value):
        if len(tokens) > 1:
            tokens.append((True, ","))
        tokens.append((False, item))
    return [*tokens, (True, "]")]


def encode_json(value: object) -> str:
    """Encode parser-supported nesting without recursive Python calls."""
    pending: list[tuple[bool, object]] = [(False, value)]
    encoded: list[str] = []
    while pending:
        literal, current = pending.pop()
        if literal:
            encoded.append(cast(str, current))
        elif isinstance(current, (dict, list)):
            pending.extend(reversed(_container_tokens(cast(object, current))))
        else:
            encoded.append(_scalar(current))
    return "".join(encoded)


def _scalar_equal(left: object, right: object) -> bool:
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return left == right and (not left.is_zero() or left.is_signed() == right.is_signed())
    return left == right


def _child_pairs(left: object, right: object) -> list[tuple[object, object]] | None:
    if isinstance(left, dict) and isinstance(right, dict):
        left, right = cast(dict[str, object], left), cast(dict[str, object], right)
        if left.keys() != right.keys():
            return None
        return [(value, right[key]) for key, value in left.items()]
    if isinstance(left, list) and isinstance(right, list):
        left, right = cast(list[object], left), cast(list[object], right)
        return list(zip(left, right, strict=True)) if len(left) == len(right) else None
    return [] if _scalar_equal(cast(object, left), right) else None


def equal_json(left: object, right: object) -> bool:
    """Ignore object order while retaining array order and JSON numeric types."""
    pending = [(left, right)]
    while pending:
        left, right = pending.pop()
        left = Decimal(str(left)) if isinstance(left, float) else left
        right = Decimal(str(right)) if isinstance(right, float) else right
        if type(left) is not type(right):
            return False
        children = _child_pairs(left, right)
        if children is None:
            return False
        pending.extend(children)
    return True
