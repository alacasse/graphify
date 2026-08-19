"""Byte-preserving operations for Graphify-owned Markdown sections."""

from __future__ import annotations


def _h1_section_spans(content: bytes, heading: bytes) -> list[tuple[int, int]]:
    """Return spans for exact H1 sections named by *heading*."""
    lines: list[tuple[int, int, bytes]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        end = offset + len(line)
        lines.append((offset, end, line.rstrip(b"\r\n")))
        offset = end

    spans: list[tuple[int, int]] = []
    for index, (start, _end, body) in enumerate(lines):
        if body != heading:
            continue
        section_end = len(content)
        for next_start, _next_end, next_body in lines[index + 1 :]:
            if next_body.startswith(b"# "):
                section_end = next_start
                break
        spans.append((start, section_end))
    return spans


def _validate_h1_heading(heading: bytes) -> None:
    if not heading.startswith(b"# ") or b"\n" in heading or b"\r" in heading:
        raise ValueError("heading must be a single H1 line")


def replace_h1_sections(content: bytes, *, heading: bytes, replacement: bytes) -> bytes:
    """Replace all exact *heading* sections with one canonical section.

    Bytes outside the owned H1 sections are returned unchanged. A missing
    section is appended without rewriting the preceding user content.
    """
    _validate_h1_heading(heading)

    canonical = replacement.strip(b"\r\n") + b"\n"
    spans = _h1_section_spans(content, heading)
    if not spans:
        if not content:
            return canonical
        if content.endswith((b"\n\n", b"\r\n\r\n")):
            separator = b""
        elif content.endswith((b"\n", b"\r")):
            separator = b"\n"
        else:
            separator = b"\n\n"
        return content + separator + canonical

    prefix = content[: spans[0][0]]
    preserved = bytearray()
    cursor = spans[0][1]
    for start, end in spans[1:]:
        preserved.extend(content[cursor:start])
        cursor = end
    preserved.extend(content[cursor:])

    separator = b"\n" if preserved else b""
    return prefix + canonical + separator + bytes(preserved)


def remove_h1_sections(content: bytes, *, heading: bytes) -> bytes:
    """Remove all exact *heading* sections without rewriting other bytes."""
    _validate_h1_heading(heading)
    spans = _h1_section_spans(content, heading)
    if not spans:
        return content

    cleaned = bytearray(content[: spans[0][0]])
    cursor = spans[0][1]
    for start, end in spans[1:]:
        cleaned.extend(content[cursor:start])
        cursor = end
    cleaned.extend(content[cursor:])
    return bytes(cleaned)
