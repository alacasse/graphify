"""Bounded streaming capture for one supervised subprocess."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from tools.install_sandbox.validation.protocol import StreamCapture


@dataclass(slots=True)
class BoundedCapture:
    limit: int
    data: bytearray
    total_bytes: int = 0
    error: str | None = None

    @classmethod
    def open(cls, limit: int) -> BoundedCapture:
        return cls(limit, bytearray())

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])

    def finish(self, *, process_complete: bool) -> StreamCapture:
        omitted = self.total_bytes - len(self.data)
        return StreamCapture(
            bytes(self.data),
            process_complete and omitted == 0 and self.error is None,
            omitted,
            self.error,
        )


def pump_stream(stream: BinaryIO, capture: BoundedCapture) -> None:
    """Drain one pipe while retaining only the configured byte prefix."""

    try:
        while chunk := stream.read(64 * 1024):
            capture.append(chunk)
    except OSError as error:
        capture.error = str(error)
    finally:
        stream.close()
