"""Rubric-based LLM-judge grader.

The judge is decoupled from any provider SDK via an injected ``model_call``
function ``(prompt, model) -> raw_text``. Hardening matches the geval grader:

- the judge model is PINNED (``cfg.judge_model``, falling back to a stable
  default) and called at temperature 0 *by contract* — the injected
  ``model_call`` is expected to pin temp 0 for this judge model;
- the prompt forces a single normalized score in ``[0, 1]`` which is parsed
  defensively and clamped.

The judge must be independent of the target/optimizer model (caller's
responsibility when wiring ``model_call``).
"""

from __future__ import annotations

import re
from typing import Optional

from ..domain import DatasetCase, GraderConfig
from .base import ModelCallFn, clamp

_DEFAULT_JUDGE_MODEL = "gpt-4o-mini"

_SCORE_RE = re.compile(r"(-?\d+(?:\.\d+)?)")

_PROMPT_TEMPLATE = """You are a strict evaluation judge. Score how well the PREDICTION satisfies the rubric given the GROUND TRUTH.

RUBRIC:
{rubric}

QUESTION/INPUT:
{question}

GROUND TRUTH:
{ground_truth}

PREDICTION:
{prediction}

Respond with ONLY a single number between 0 and 1 (inclusive), where 1 means the prediction fully satisfies the rubric and 0 means it fails entirely. No words, just the number."""


def _parse_score(raw: str) -> float:
    """Extract the first number from the judge's reply and clamp to ``[0, 1]``.

    Accepts a bare float, an ``"x/y"`` form, or a percentage; anything else
    degrades to 0.0.
    """
    text = (raw or "").strip()
    # percentage form e.g. "85%"
    pct = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return clamp(float(pct.group(1)) / 100.0)
    # fraction form e.g. "4/5"
    frac = re.search(r"(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if frac:
        denom = float(frac.group(2))
        return clamp(float(frac.group(1)) / denom) if denom else 0.0
    m = _SCORE_RE.search(text)
    if not m:
        return 0.0
    val = float(m.group(1))
    # Heuristic: a lone number >1 is likely a 0..100 scale.
    if val > 1.0:
        val = val / 100.0
    return clamp(val)


class LLMJudgeGrader:
    """Rubric judge backed by an injected model-call function."""

    def __init__(self, cfg: GraderConfig, model_call: ModelCallFn) -> None:
        self._rubric = cfg.rubric or "Is the prediction correct and complete?"
        self._model = cfg.judge_model or _DEFAULT_JUDGE_MODEL
        self._model_call = model_call

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        prompt = _PROMPT_TEMPLATE.format(
            rubric=self._rubric,
            question=item.input if item is not None else "",
            ground_truth=ground_truth,
            prediction=prediction,
        )
        try:
            raw = self._model_call(prompt, self._model)
        except Exception:  # noqa: BLE001 - a judge failure scores 0, never crashes
            return 0.0
        return _parse_score(raw)


__all__ = ["LLMJudgeGrader"]
