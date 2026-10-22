"""Portable verdict for the package preparation gate."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PreparationResult:
    status: Literal["prepared", "nonconformant", "incomplete"]
    diagnostics: tuple[str, ...] = ()
    binding: dict[str, str] | None = None

    def to_data(self) -> dict[str, object]:
        return {
            "status": self.status,
            "diagnostics": list(self.diagnostics),
            "binding": self.binding,
        }
