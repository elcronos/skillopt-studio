"""Graders API.

Endpoints:
- ``GET  /api/graders/types``         — list available grader types (geval flagged
                                         disabled when deepeval is absent).
- ``POST /api/graders/dry-run``       — score a single sample with a GraderConfig.
- ``GET  /api/graders/recommend``     — recommend a grader for a stored dataset.
- ``GET  /api/graders/estimate-cost`` — estimate judge-call volume for a dataset.

The dry-run for ``llm_judge`` requires a wired model-call fn which the studio
does not expose here, so dry-run supports the dependency-free + custom graders
and reports ``geval`` availability without invoking a paid judge.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..dataset import store as dataset_store
from ..domain import DatasetCase, GraderConfig, GraderType
from ..grading import deepeval_available, estimate_judge_calls, make_grader, recommend_grader

router = APIRouter(prefix="/api/graders", tags=["graders"])


class DryRunRequest(BaseModel):
    """Score one (prediction, ground_truth) pair with a grader config."""

    config: GraderConfig
    prediction: str
    ground_truth: str
    item: Optional[DatasetCase] = None


class DryRunResponse(BaseModel):
    soft: float
    hard: int
    type: str


@router.get("/types")
def list_types() -> list[dict[str, Any]]:
    """List grader types and whether each is currently usable."""
    out: list[dict[str, Any]] = []
    for t in GraderType:
        entry: dict[str, Any] = {"type": t.value, "available": True}
        if t == GraderType.geval:
            entry["available"] = deepeval_available()
            if not entry["available"]:
                entry["note"] = "Install the optional [geval] extra (deepeval) to enable."
        if t == GraderType.custom_python:
            entry["note"] = "Requires explicit consent; runs in the honest-mistake sandbox."
        out.append(entry)
    return out


@router.post("/dry-run")
def dry_run(req: DryRunRequest) -> DryRunResponse:
    """Score a single sample. ``llm_judge`` is rejected (no judge wired here)."""
    if req.config.type == GraderType.llm_judge:
        raise HTTPException(
            status_code=400,
            detail="llm_judge dry-run is not supported here (no judge model wired).",
        )
    try:
        grader = make_grader(req.config)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    soft = grader.score(req.prediction, req.ground_truth, item=req.item)
    hard = int(soft >= req.config.threshold)
    return DryRunResponse(soft=soft, hard=hard, type=req.config.type.value)


@router.get("/recommend")
def recommend(dataset: str) -> dict[str, str]:
    """Recommend a grader for a stored dataset (by name/slug)."""
    ds = dataset_store.get(dataset)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset}' not found")
    return recommend_grader(ds)


@router.get("/estimate-cost")
def estimate_cost(
    dataset: str,
    num_epochs: int = 1,
    num_steps: int = 0,
    self_consistency: int = 1,
) -> dict[str, Any]:
    """Estimate judge-call volume for a geval/llm_judge run over a dataset."""
    ds = dataset_store.get(dataset)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset}' not found")
    return estimate_judge_calls(
        ds,
        {
            "num_epochs": num_epochs,
            "num_steps": num_steps,
            "self_consistency": self_consistency,
        },
    )
