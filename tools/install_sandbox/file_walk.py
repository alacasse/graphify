from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def pruned_file_walk(base: Path, prune_dirs: Iterable[str]) -> Iterable[Path]:
    if not base.exists():
        return
    prune = set(prune_dirs)
    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in prune)
        for name in sorted(files):
            yield root_path / name
