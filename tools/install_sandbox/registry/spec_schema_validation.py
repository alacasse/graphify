from __future__ import annotations

from typing import AbstractSet, Mapping


class SpecSchemaValidationError(ValueError):
    pass


SCHEMA_CLASS_TARGET_FACT = "target_fact"
SCHEMA_CLASS_TRANSITIONAL_EXECUTION = "transitional_execution"
SCHEMA_CLASS_TRANSITIONAL_PLANNING = "transitional_planning"
SCHEMA_CLASS_HARNESS_POLICY_INPUT = "harness_policy_input"
SCHEMA_CLASS_PUBLIC_SCHEMA_COMPATIBILITY = "public_schema_compatibility"
SCHEMA_CLASS_PUBLIC_PRODUCT_CONTRACT = "public_product_contract"

PUBLIC_SCHEMA_COMPATIBILITY_FIELDS = frozenset(
    {
        "platforms",
        "eligible_platform_scope",
    }
)
PUBLIC_PRODUCT_CONTRACT_FIELDS = frozenset({"--platform"})


def reject_unknown_fields(data: Mapping[str, object], allowed: AbstractSet[str], context: str) -> None:
    unknown = sorted(str(key) for key in data if key not in allowed)
    if not unknown:
        return
    if len(unknown) == 1:
        raise SpecSchemaValidationError(f"{context}: unknown field: {unknown[0]}")
    raise SpecSchemaValidationError(f"{context}: unknown fields: {', '.join(unknown)}")
