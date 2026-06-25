from __future__ import annotations

try:
    from .registry.spec_normalize import normalize_registry
except ImportError:  # pragma: no cover - direct script import fallback
    from registry.spec_normalize import normalize_registry  # type: ignore[no-redef]

__all__ = ["normalize_registry"]
