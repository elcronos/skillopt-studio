"""DeepEval G-Eval grader (optional dependency, hardened).

G-Eval is best for open-ended / free-text skills with no canonical answer; for
verifiable answers prefer exact/f1. DeepEval is an OPTIONAL dependency (extra
``[geval]``). The import is GUARDED: if ``deepeval`` is not installed the grader
constructs fine but is DISABLED — :meth:`available` is False and :meth:`score`
returns 0.0 after logging a one-time clear message. Importing this module never
crashes.

Hardening (mandatory — SkillOpt warns noisy metrics confuse the optimizer):

- judge model is PINNED (``cfg.judge_model``) and run at TEMPERATURE 0;
- optional SELF-CONSISTENCY: average of ``cfg.self_consistency`` (N>=1) calls;
- RESULT CACHE keyed by ``(skill_version_hash, case_id, judge_model)`` so
  unchanged skill outputs are never re-judged — pass ``skill_version_hash`` via
  :meth:`set_skill_version`;
- the judge is INDEPENDENT of the target/optimizer model (caller wires a
  separate judge model);
- judge model + criteria are exposed via :meth:`metadata` for run records.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from ..domain import DatasetCase, GraderConfig
from .base import clamp

logger = logging.getLogger("skillopt_studio.grading.geval")

_DEFAULT_JUDGE_MODEL = "gpt-4o-mini"

# Guarded optional import. ``_DEEPEVAL_ERR`` records why it is unavailable.
_DEEPEVAL_AVAILABLE = False
_DEEPEVAL_ERR: Optional[str] = None
try:  # pragma: no cover - exercised only where deepeval is installed
    from deepeval.metrics import GEval as _GEval
    from deepeval.test_case import LLMTestCase as _LLMTestCase
    from deepeval.test_case import LLMTestCaseParams as _Params

    _DEEPEVAL_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001 - any import failure disables the grader
    _GEval = None  # type: ignore[assignment]
    _LLMTestCase = None  # type: ignore[assignment]
    _Params = None  # type: ignore[assignment]
    _DEEPEVAL_ERR = str(_exc)


_DISABLED_MSG = (
    "geval grader DISABLED: the optional 'deepeval' dependency is not installed. "
    "Install with `pip install -e \".[geval]\"`. Falling back to score 0.0. "
    "(exact/fuzzy/f1 graders are always available.)"
)


def deepeval_available() -> bool:
    """Return True when the optional ``deepeval`` dependency is importable."""
    return _DEEPEVAL_AVAILABLE


class GEvalGrader:
    """G-Eval metric wrapper with pinning, self-consistency, and caching."""

    def __init__(self, cfg: GraderConfig) -> None:
        self._criteria = cfg.criteria
        self._evaluation_steps = cfg.evaluation_steps
        self._judge_model = cfg.judge_model or _DEFAULT_JUDGE_MODEL
        self._n = max(1, int(cfg.self_consistency or 1))
        # cache: (skill_version_hash, case_id, judge_model) -> soft score
        self._cache: dict[tuple[str, str, str], float] = {}
        self._skill_version_hash: str = ""
        self._warned = False
        self._metric = None  # built lazily so disabled state never touches deepeval

        if (
            _DEEPEVAL_AVAILABLE
            and not self._criteria
            and not self._evaluation_steps
        ):
            # DeepEval requires one of criteria/evaluation_steps; default sensibly.
            self._criteria = "Determine whether the prediction is correct and complete."

    # --- hardening hooks -----------------------------------------------------
    def set_skill_version(self, skill_version_hash: str) -> None:
        """Set the current skill-version hash used in the cache key."""
        self._skill_version_hash = str(skill_version_hash or "")

    def available(self) -> bool:
        """Whether this grader can actually score (deepeval present)."""
        return _DEEPEVAL_AVAILABLE

    def metadata(self) -> dict[str, object]:
        """Judge model + criteria for the run record (no secrets)."""
        return {
            "grader": "geval",
            "judge_model": self._judge_model,
            "criteria": self._criteria,
            "evaluation_steps": self._evaluation_steps,
            "self_consistency": self._n,
            "deepeval_available": _DEEPEVAL_AVAILABLE,
        }

    # --- scoring -------------------------------------------------------------
    def _build_metric(self):
        if self._metric is not None:
            return self._metric
        # Pin temperature 0 for the judge. DeepEval reads the model name; temp is
        # pinned via env so the judge is deterministic regardless of caller.
        os.environ.setdefault("DEEPEVAL_TEMPERATURE", "0")
        kwargs: dict[str, object] = {
            "name": "skillopt-geval",
            "model": self._judge_model,
            "evaluation_params": [_Params.INPUT, _Params.ACTUAL_OUTPUT, _Params.EXPECTED_OUTPUT],
        }
        if self._evaluation_steps:
            kwargs["evaluation_steps"] = list(self._evaluation_steps)
        else:
            kwargs["criteria"] = self._criteria
        self._metric = _GEval(**kwargs)  # type: ignore[misc]
        return self._metric

    def _measure_once(self, prediction: str, ground_truth: str, question: str) -> float:
        metric = self._build_metric()
        test_case = _LLMTestCase(  # type: ignore[misc]
            input=question,
            actual_output=prediction,
            expected_output=ground_truth,
        )
        metric.measure(test_case)
        # DeepEval scores are already normalized to 0..1.
        return clamp(getattr(metric, "score", 0.0) or 0.0)

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        if not _DEEPEVAL_AVAILABLE:
            if not self._warned:
                logger.warning(_DISABLED_MSG + " (import error: %s)", _DEEPEVAL_ERR)
                self._warned = True
            return 0.0

        case_id = item.id if item is not None else ""
        cache_key = (self._skill_version_hash, case_id, self._judge_model)
        # Only cache when we have a stable identity (hash + case id); ad-hoc
        # dry-runs without those keys are not cached to avoid stale collisions.
        cacheable = bool(self._skill_version_hash) and bool(case_id)
        if cacheable and cache_key in self._cache:
            return self._cache[cache_key]

        question = item.input if item is not None else ""
        scores: list[float] = []
        for _ in range(self._n):
            try:
                scores.append(self._measure_once(prediction, ground_truth, question))
            except Exception:  # noqa: BLE001 - a judge failure scores 0 for that call
                logger.exception("geval measure failed; scoring 0 for this call")
                scores.append(0.0)
        soft = clamp(sum(scores) / len(scores)) if scores else 0.0

        if cacheable:
            self._cache[cache_key] = soft
        return soft


__all__ = ["GEvalGrader", "deepeval_available"]
