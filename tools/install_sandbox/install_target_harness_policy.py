from __future__ import annotations

try:
    from .targets import install_target_harness_policy as _owner
except ImportError:  # pragma: no cover - direct script import fallback
    from targets import install_target_harness_policy as _owner  # type: ignore[no-redef]

globals().update({name: value for name, value in vars(_owner).items() if not (name.startswith("__") and name.endswith("__"))})
