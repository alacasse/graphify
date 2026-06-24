from __future__ import annotations

try:
    from .surfaces.install_surface_statuses import *  # noqa: F401,F403
except ImportError:  # pragma: no cover - direct script import fallback
    from surfaces.install_surface_statuses import *  # type: ignore[no-redef] # noqa: F401,F403
