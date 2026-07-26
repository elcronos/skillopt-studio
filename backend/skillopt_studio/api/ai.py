"""AI-generation API (drafts into the existing editors; never auto-applies).

Endpoints draft dataset cases, G-Eval criteria, and a custom-Python scorer from a
skill body + a short user instruction, using the local ``claude`` CLI. The skill
body is resolved from a ``skill_id`` (via the scanner registry) or supplied
directly as ``skill_body`` in the request.

Failures from the CLI surface as 503 (so the UI can disable AI controls); an
unknown ``skill_id`` is 404. Prompts are not logged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..ai import (
    ClaudeCLIError,
    claude_available,
    generate_custom_scorer,
    generate_dataset_cases,
    generate_geval_criteria,
)
from ..scanner.registry import scan_all

logger = logging.getLogger("skillopt_studio.api.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])


# --- Request models ---------------------------------------------------------
class _SkillContext(BaseModel):
    """Shared skill-context fields. Provide ``skill_id`` OR ``skill_body``."""

    skill_id: Optional[str] = None
    skill_body: Optional[str] = None
    instruction: str = Field(min_length=1)


class GenerateDatasetRequest(_SkillContext):
    count: int = 10


class GenerateGevalRequest(_SkillContext):
    pass


class GenerateScorerRequest(_SkillContext):
    pass


# --- Helpers ----------------------------------------------------------------
def _get_cwd() -> Path:
    try:
        return Path.cwd()
    except OSError:
        return Path.home()


def _resolve_skill_body(skill_id: Optional[str], skill_body: Optional[str]) -> str:
    """Return the skill body from an explicit body or by resolving ``skill_id``.

    Raises 404 if ``skill_id`` is given but not found. Returns "" when neither is
    supplied (instruction-only generation is allowed).
    """
    if skill_body and skill_body.strip():
        return skill_body
    if not skill_id:
        return ""
    try:
        skills = scan_all(_get_cwd())
    except Exception:  # noqa: BLE001 - scanner should not raise, but stay defensive
        logger.warning("ai: skill scan failed while resolving skill_id")
        skills = []
    for skill in skills:
        if skill.id == skill_id:
            return skill.body or ""
    raise HTTPException(status_code=404, detail=f"skill '{skill_id}' not found")


def _cli_error(exc: ClaudeCLIError) -> HTTPException:
    return HTTPException(
        status_code=503, detail=f"claude CLI not available / failed: {exc}"
    )


# --- Endpoints --------------------------------------------------------------
@router.get("/available")
def available() -> dict[str, bool]:
    """Report whether the ``claude`` CLI is usable (for hiding/disabling UI)."""
    return {"available": claude_available()}


@router.post("/generate-dataset")
def generate_dataset(req: GenerateDatasetRequest) -> dict[str, Any]:
    """Draft dataset cases; returns ``{"cases": [...]}`` for the editor."""
    body = _resolve_skill_body(req.skill_id, req.skill_body)
    try:
        cases = generate_dataset_cases(body, req.instruction, count=req.count)
    except ClaudeCLIError as exc:
        raise _cli_error(exc) from exc
    return {"cases": cases}


@router.post("/generate-geval")
def generate_geval(req: GenerateGevalRequest) -> dict[str, Any]:
    """Draft G-Eval criteria + steps; returns ``{"criteria":[...],
    "evaluation_steps":[...]}``."""
    body = _resolve_skill_body(req.skill_id, req.skill_body)
    try:
        result = generate_geval_criteria(body, req.instruction)
    except ClaudeCLIError as exc:
        raise _cli_error(exc) from exc
    return result


@router.post("/generate-scorer")
def generate_scorer(req: GenerateScorerRequest) -> dict[str, str]:
    """Draft a custom-Python scorer; returns ``{"custom_code": str}``."""
    body = _resolve_skill_body(req.skill_id, req.skill_body)
    try:
        result = generate_custom_scorer(body, req.instruction)
    except ClaudeCLIError as exc:
        raise _cli_error(exc) from exc
    return result
