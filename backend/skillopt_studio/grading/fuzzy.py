"""Fuzzy-match grader (deterministic, dependency-free).

Uses the stdlib ``difflib.SequenceMatcher`` ratio over normalized strings, so it
needs no third-party fuzzy-string library. Returns the similarity ratio in
``[0, 1]`` (1.0 for identical normalized strings).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from ..domain import DatasetCase
from .base import clamp


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


class FuzzyGrader:
    """Character-sequence similarity ratio in ``[0, 1]``."""

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        pred = _normalize(prediction)
        truth = _normalize(ground_truth)
        if not pred and not truth:
            return 1.0
        return clamp(SequenceMatcher(None, pred, truth).ratio())


__all__ = ["FuzzyGrader"]
