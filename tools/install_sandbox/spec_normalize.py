from __future__ import annotations

try:
    from .registry import spec_normalize as _owner
except ImportError:  # pragma: no cover - direct script import fallback
    from registry import spec_normalize as _owner  # type: ignore[no-redef]

globals().update({name: getattr(_owner, name) for name in dir(_owner) if not name.startswith("__")})
