"""Temporary intra-batch forwarding for Slice 2.

Slice 3 must migrate production imports to
``tools.install_sandbox.targets.reference_resolution`` and delete this module.
"""

from __future__ import annotations

from .targets.reference_resolution import (
    PackagedReferenceResolution,
    ReferenceBundleFact,
    ReferenceResolutionStatus,
    TargetReferenceFacts,
    package_dir_from_main_module,
    resolve_target_packaged_references,
)

__all__ = [
    "PackagedReferenceResolution",
    "ReferenceBundleFact",
    "ReferenceResolutionStatus",
    "TargetReferenceFacts",
    "package_dir_from_main_module",
    "resolve_target_packaged_references",
]
