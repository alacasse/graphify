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


def rewrite_frontmatter_fields(
    content: bytes, *, fields: tuple[tuple[bytes, bytes], ...]
) -> bytes:
    """Rewrite only selected root YAML fields, preserving all other bytes."""
    for key, value in fields:
        if not key or any(token in key for token in (b":", b"\r", b"\n")):
            raise ValueError("frontmatter field keys must be plain single-line names")
        if b"\r" in value or b"\n" in value:
            raise ValueError("frontmatter field values must be single-line bytes")

    lines = content.splitlines(keepends=True)
    has_opening = bool(lines) and lines[0].rstrip(b"\r\n") == b"---"
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip(b"\r\n") == b"---"
        ),
        None,
    )
    if not has_opening or closing_index is None:
        frontmatter = b"---\n" + b"".join(
            key + b": " + value + b"\n" for key, value in fields
        )
        return frontmatter + b"---\n\n" + content

    default_ending = lines[0][len(lines[0].rstrip(b"\r\n")) :] or b"\n"
    rewritten = list(lines)
    seen: set[bytes] = set()
    for index in range(1, closing_index):
        line = lines[index]
        body = line.rstrip(b"\r\n")
        ending = line[len(body) :]
        for key, value in fields:
            if body.startswith(key + b":"):
                rewritten[index] = key + b": " + value + ending
                seen.add(key)
                break

    missing = [
        key + b": " + value + default_ending
        for key, value in fields
        if key not in seen
    ]
    if missing:
        rewritten[closing_index:closing_index] = missing
    return b"".join(rewritten)
