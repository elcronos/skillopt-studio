"""Exact-match grader (deterministic, dependency-free).

Scores 1.0 when the normalized prediction equals the normalized ground truth,
else 0.0. Normalization lowercases and collapses surrounding/inner whitespace so
that trivial formatting differences do not count as mismatches.
"""

from __future__ import annotations

from typing import Optional

from ..domain import DatasetCase
from .base import clamp


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


class ExactGrader:
    """1.0 on normalized exact match, else 0.0."""

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        return clamp(1.0 if _normalize(prediction) == _normalize(ground_truth) else 0.0)


__all__ = ["ExactGrader"]
