"""Grading subsystem for the generic_qa adapter.

A ``Grader`` (see :mod:`grading.base`) maps a prediction + ground truth to a
``soft`` score in ``[0, 1]``. Build one with :func:`make_grader` from a
``GraderConfig``. Graders:

- ``exact`` / ``fuzzy`` / ``f1`` — deterministic, dependency-free.
- ``llm_judge`` — rubric judge via an injected model-call fn (pinned, temp 0).
- ``geval`` — DeepEval G-Eval (OPTIONAL dep ``[geval]``; disabled with a clear
  message when absent — never crashes imports).
- ``custom_python`` — user scorer in the honest-mistake sandbox.

:func:`recommend_grader` / :func:`estimate_judge_calls` power the "analyse
workflow & suggest" UI hint and the pre-run cost warning.
"""

from __future__ import annotations

import json as _json
from typing import Any, Callable, Optional

from ..domain import DatasetCase, GraderConfig, GraderType
from .base import Grader, ModelCallFn, make_grader, clamp
from .recommender import recommend_grader, estimate_judge_calls
from .geval import deepeval_available


def _coerce_ground_truth(ground_truth: Any) -> str:
    """Normalize a list/dict/scalar ground_truth into the single string the
    deterministic graders + judges expect.

    The generic_qa env may pass a list (multiple acceptable answers) or a dict
    (``{"answer": ...}`` / ``{"answers": [...]}``) via ``_coerce_gold``. We pick a
    representative string: first list element, the ``answer``/``answers`` value of
    a dict, else the compact JSON / str form.
    """
    if ground_truth is None:
        return ""
    if isinstance(ground_truth, str):
        return ground_truth
    if isinstance(ground_truth, (list, tuple)):
        return str(ground_truth[0]) if ground_truth else ""
    if isinstance(ground_truth, dict):
        if isinstance(ground_truth.get("answers"), (list, tuple)) and ground_truth["answers"]:
            return str(ground_truth["answers"][0])
        if "answer" in ground_truth:
            return str(ground_truth["answer"])
        return _json.dumps(ground_truth, sort_keys=True, ensure_ascii=False)
    return str(ground_truth)


def _coerce_item(item: Any) -> Optional[DatasetCase]:
    """Best-effort coerce an env item (dict) into a DatasetCase for graders."""
    if item is None:
        return None
    if isinstance(item, DatasetCase):
        return item
    if isinstance(item, dict):
        try:
            return DatasetCase(
                id=str(item.get("id", "")),
                input=str(item.get("input", "")),
                ground_truth=_coerce_ground_truth(item.get("ground_truth")),
                metadata=item.get("metadata") or {},
            )
        except Exception:  # noqa: BLE001
            return None
    return None


def score(
    *,
    scoring_type: str,
    prediction: str,
    ground_truth: Any = None,
    item: Any = None,
    judge_model: str = "",
    rubric: str = "",
    criteria: str = "",
    custom_code: str = "",
    threshold: float = 0.5,
    self_consistency: int = 1,
    custom_consent: bool = True,
    model_call: Optional[Callable[[str, str], str]] = None,
    **_ignored: Any,
) -> float:
    """Module-level adapter the generic_qa env calls: build a ``GraderConfig`` +
    ``make_grader`` and return the clamped soft score in ``[0, 1]``.

    This is the single bridge between the env's flat scoring spec and the grader
    factory. ``ground_truth`` may arrive as a list/dict (env ``_coerce_gold``
    shape) and is normalized here. For ``llm_judge``/``geval`` a ``model_call``
    judge function may be injected (the env binds it to SkillOpt's model layer);
    when absent, ``llm_judge`` cannot run and raises (so the env does NOT silently
    fall back to f1 — the caller surfaces the misconfiguration), and ``geval``
    uses DeepEval directly (disabled→0.0 when the optional dep is missing).
    """
    try:
        gtype = GraderType(str(scoring_type).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unknown scoring_type: {scoring_type!r}") from exc

    cfg = GraderConfig(
        type=gtype,
        threshold=clamp(threshold),
        rubric=rubric or None,
        judge_model=judge_model or None,
        criteria=criteria or None,
        custom_code=custom_code or None,
        self_consistency=max(1, int(self_consistency or 1)),
        custom_consent=bool(custom_consent),
    )
    grader = make_grader(cfg, model_call=model_call)
    gt = _coerce_ground_truth(ground_truth)
    case = _coerce_item(item)
    return clamp(grader.score(prediction, gt, item=case))


__all__ = [
    "Grader",
    "ModelCallFn",
    "make_grader",
    "clamp",
    "score",
    "recommend_grader",
    "estimate_judge_calls",
    "deepeval_available",
]
