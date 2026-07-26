"""Grader protocol + factory.

A ``Grader`` maps a prediction + ground truth (with the optional originating
``DatasetCase``) to a ``soft`` score in ``[0, 1]``. ``make_grader`` builds the
concrete grader from a ``GraderConfig``. Every score returned through this layer
is clamped to ``[0, 1]`` via :func:`clamp` so a misbehaving grader (or user
scorer) can never poison the optimizer with out-of-range values.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from ..domain import DatasetCase, GraderConfig, GraderType

# A model-call function injected into LLM-based graders. It takes a fully-formed
# prompt + the pinned judge model name and returns the raw model text. Keeping it
# injected means graders never import a provider SDK and stay testable.
ModelCallFn = Callable[[str, str], str]


def clamp(value: float) -> float:
    """Clamp ``value`` into ``[0, 1]``; coerce non-finite/non-numeric to 0.0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


@runtime_checkable
class Grader(Protocol):
    """Protocol all graders satisfy."""

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        """Return a ``soft`` score in ``[0, 1]``."""
        ...


def make_grader(
    cfg: GraderConfig,
    *,
    model_call: Optional[ModelCallFn] = None,
) -> Grader:
    """Build a concrete :class:`Grader` from ``cfg``.

    ``model_call`` is required for ``llm_judge`` (and used as a fallback path is
    not provided for ``geval``, which uses DeepEval directly). Imports of
    concrete graders are local so optional dependencies (DeepEval) never break
    construction of the deterministic graders.
    """
    t = cfg.type
    if t == GraderType.exact:
        from .exact import ExactGrader

        return ExactGrader()
    if t == GraderType.fuzzy:
        from .fuzzy import FuzzyGrader

        return FuzzyGrader()
    if t == GraderType.f1:
        from .f1 import F1Grader

        return F1Grader()
    if t == GraderType.llm_judge:
        from .llm_judge import LLMJudgeGrader

        if model_call is None:
            raise ValueError("llm_judge grader requires a model_call function")
        return LLMJudgeGrader(cfg, model_call)
    if t == GraderType.geval:
        from .geval import GEvalGrader

        return GEvalGrader(cfg)
    if t == GraderType.custom_python:
        from .custom import CustomPythonGrader

        return CustomPythonGrader(cfg)

    raise ValueError(f"unknown grader type: {t!r}")


__all__ = ["Grader", "ModelCallFn", "make_grader", "clamp"]
