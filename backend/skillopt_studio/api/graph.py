"""Structure-graph API router.

Exposes:
- ``GET /api/skills/{id}/graph`` — load the skill (via the provider scanner),
  run its markdown through the Node graph sidecar (bundled SkillForge
  deterministic parser), and return ``{mermaid, nodes, edges, crossRefs, ...}``.
  On sidecar failure the response degrades to ``{error, rawMarkdown}`` (HTTP 200)
  rather than a 500, so the frontend can render the raw markdown.

Skill loading is defensive: the scanner registry is imported lazily so this
router still mounts (and can serve graphs from an inline ``body`` query param)
even if the scanner package is not importable. When the scanner is available but
the id is unknown, callers may still supply the markdown directly via ``?body=``;
otherwise a 404 is returned.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from ..graph import GraphSidecarError, build_graph, fallback_result

logger = logging.getLogger("skillopt_studio.api.graph")

router = APIRouter(prefix="/api", tags=["graph"])


def _load_skill_body(skill_id: str) -> Optional[str]:
    """Return the markdown body for ``skill_id`` via the scanner, or ``None``.

    Imports the scanner registry lazily and defensively: if the scanner package
    is not importable, or scanning raises, this returns ``None`` (treated as
    "not ready / not found" by the caller).
    """
    try:
        from ..scanner.registry import scan_all
    except Exception:  # noqa: BLE001 - scanner package not built/available yet
        logger.warning("graph: scanner registry not importable; skill lookup skipped")
        return None

    try:
        cwd = Path.cwd()
    except OSError:
        cwd = Path.home()

    try:
        skills = scan_all(cwd)
    except Exception:  # noqa: BLE001 - scan failures degrade to "not found"
        logger.exception("graph: scan_all raised unexpectedly")
        return None

    for skill in skills:
        if skill.id == skill_id:
            return skill.body

    return None


@router.get("/skills/{skill_id}/graph")
def skill_graph(
    skill_id: str,
    body: Optional[str] = Query(
        default=None,
        description=(
            "Optional raw skill markdown. Used when the scanner is not ready or "
            "the id is unknown; lets the frontend graph an unsaved/edited skill."
        ),
    ),
) -> dict[str, Any]:
    """Return the deterministic structure graph for a skill.

    Resolution order for the markdown source:
    1. The ``body`` query param, if provided (graph an inline/edited skill).
    2. The scanner registry, looked up by ``skill_id``.

    If neither yields markdown, returns 404. Sidecar failures return the fallback
    payload (``{error, rawMarkdown, ...}``) with HTTP 200.
    """
    markdown = body if body is not None else _load_skill_body(skill_id)

    if markdown is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Skill '{skill_id}' not found and no inline 'body' provided. "
                "Pass ?body=<markdown> to graph an unsaved skill."
            ),
        )

    try:
        return build_graph(markdown)
    except GraphSidecarError as exc:
        logger.warning("graph: sidecar failed for skill '%s': %s", skill_id, exc)
        return fallback_result(str(exc), markdown)
