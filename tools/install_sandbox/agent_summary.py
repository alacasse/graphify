from __future__ import annotations

try:
    from .reporting.agent_summary import (
        USAGE_GUIDANCE,
        artifact_relpath,
        compact_path,
        failed_checks,
        load_json,
        main,
        parse_args,
        render_json,
        render_markdown,
        summarize_incomplete,
        summarize_output,
        tail_file,
        text_snippet,
        write_summary,
    )
except ImportError:  # pragma: no cover - supports running this file directly.
    from reporting.agent_summary import (  # type: ignore[no-redef]
        USAGE_GUIDANCE,
        artifact_relpath,
        compact_path,
        failed_checks,
        load_json,
        main,
        parse_args,
        render_json,
        render_markdown,
        summarize_incomplete,
        summarize_output,
        tail_file,
        text_snippet,
        write_summary,
    )

__all__ = [
    "USAGE_GUIDANCE",
    "artifact_relpath",
    "compact_path",
    "failed_checks",
    "load_json",
    "main",
    "parse_args",
    "render_json",
    "render_markdown",
    "summarize_incomplete",
    "summarize_output",
    "tail_file",
    "text_snippet",
    "write_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
