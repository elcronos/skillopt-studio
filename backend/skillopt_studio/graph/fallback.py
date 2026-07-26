"""Deterministic fallback for when the graph sidecar cannot run.

If Node is missing, the sidecar exits non-zero, or its stdout is not valid JSON,
the API still returns a well-formed payload carrying the original markdown and an
``error`` string so the frontend can degrade gracefully (e.g. render the raw
markdown instead of a diagram).
"""

from __future__ import annotations

from typing import Any


def fallback_result(error: str, raw_markdown: str) -> dict[str, Any]:
    """Return the fallback payload shape: ``{error, rawMarkdown}``.

    Kept structurally close to the sidecar's success payload (empty ``nodes``/
    ``edges`` etc.) so consumers can treat both with the same accessors.
    """
    return {
        "error": error,
        "rawMarkdown": raw_markdown,
        "mermaid": None,
        "nodes": [],
        "edges": [],
        "crossRefs": {},
    }
