"""Logical filesystem facts independent of their capture or archive location."""

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from tools.install_sandbox.contracts.results import ObservationObstacle, SnapshotEntry


@dataclass
class FilesystemSnapshot:
    entries: list[SnapshotEntry] = field(default_factory=list[SnapshotEntry])
    obstacles: list[ObservationObstacle] = field(default_factory=list[ObservationObstacle])
    contents: dict[tuple[str, str], bytes] = field(default_factory=dict[tuple[str, str], bytes])

    def entry(self, root: str, path: str) -> SnapshotEntry | None:
        return next((e for e in self.entries if (e["root"], e["path"]) == (root, path)), None)

    def absent(self, root: str, path: str) -> bool:
        """An unlisted child is absent only under a completely listed parent."""
        if self.entry(root, path) is not None:
            return False
        parent = str(PurePosixPath(path).parent)
        entry = self.entry(root, parent)
        if entry is not None:
            return entry["kind"] == "file" or (
                entry["kind"] == "directory" and entry.get("listing_complete", False)
            )
        return parent != path and self.absent(root, parent)


def same_observation(left: FilesystemSnapshot, right: FilesystemSnapshot) -> bool:
    """Compare logical observations independently of their archive locations."""

    def inventory(snapshot: FilesystemSnapshot) -> list[tuple[str, str, str, bool | None]]:
        return sorted(
            (entry["root"], entry["path"], entry["kind"], entry.get("listing_complete"))
            for entry in snapshot.entries
        )

    return (
        not left.obstacles
        and not right.obstacles
        and inventory(left) == inventory(right)
        and left.contents == right.contents
    )
