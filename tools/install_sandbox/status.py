from __future__ import annotations

"""Compatibility facade for reporting-owned status vocabulary."""

try:
    from .reporting.status import (
        RISK_GRAPHIFY_FAILED,
        RISK_GRAPHIFY_VERIFIED,
        combined_status,
        known_status_values,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from reporting.status import (  # type: ignore[no-redef]
        RISK_GRAPHIFY_FAILED,
        RISK_GRAPHIFY_VERIFIED,
        combined_status,
        known_status_values,
    )

__all__ = [
    "RISK_GRAPHIFY_FAILED",
    "RISK_GRAPHIFY_VERIFIED",
    "combined_status",
    "known_status_values",
]
