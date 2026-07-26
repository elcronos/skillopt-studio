"""Skills API router.

Exposes:
- ``GET /api/skills``        — scan all providers; returns list with provider +
                               source_path provenance.
- ``GET /api/skills/{id}``   — return full skill including body.

The router is defensive: scan failures degrade to an empty list rather than
a 500.  The ``/api/skills/{id}`` endpoint returns 404 when the skill is not
found in a fresh scan.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..domain import ProviderName, Skill
from ..scanner.registry import scan_all

logger = logging.getLogger("skillopt_studio.api.skills")

router = APIRouter(prefix="/api", tags=["skills"])


class SkillSummary(BaseModel):
    """Skill without body — returned by the list endpoint."""

    id: str
    name: str
    provider: ProviderName
    source_path: str


def _get_cwd() -> Path:
    """Return the server's cwd as the scan root; never raises."""
    try:
        return Path.cwd()
    except OSError:
        return Path.home()


@router.get("/skills", response_model=list[SkillSummary])
def list_skills() -> list[SkillSummary]:
    """Scan all providers and return skill summaries with provenance."""
    try:
        skills = scan_all(_get_cwd())
    except Exception:  # noqa: BLE001
        logger.exception("skills: scan_all raised unexpectedly")
        skills = []

    return [
        SkillSummary(
            id=s.id,
            name=s.name,
            provider=s.provider,
            source_path=s.source_path,
        )
        for s in skills
    ]


@router.get("/skills/{skill_id}", response_model=Skill)
def get_skill(skill_id: str) -> Skill:
    """Return the full skill (including body) for the given id.

    Performs a fresh scan each call so the result is always up-to-date.
    Returns 404 if the skill is not found.
    """
    try:
        skills = scan_all(_get_cwd())
    except Exception:  # noqa: BLE001
        logger.exception("skills: scan_all raised unexpectedly")
        skills = []

    for skill in skills:
        if skill.id == skill_id:
            return skill

    raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found.")
