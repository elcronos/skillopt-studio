"""Token-overlap F1 grader (deterministic, dependency-free).

Computes precision/recall over whitespace tokens (after lower-casing and basic
punctuation stripping), then the harmonic-mean F1. This is the standard
SQuAD-style token-F1 used for short-answer QA. Multiplicity is respected via a
multiset intersection so repeated tokens do not inflate the score.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from ..domain import DatasetCase
from .base import clamp

_PUNCT_RE = re.compile(r"[^\w\s]")


def _tokens(text: str) -> list[str]:
    cleaned = _PUNCT_RE.sub(" ", str(text).lower())
    return cleaned.split()


class F1Grader:
    """Token-overlap F1 in ``[0, 1]``."""

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        pred = _tokens(prediction)
        truth = _tokens(ground_truth)
        if not pred and not truth:
            return 1.0
        if not pred or not truth:
            return 0.0
        common = Counter(pred) & Counter(truth)
        overlap = sum(common.values())
        if overlap == 0:
            return 0.0
        precision = overlap / len(pred)
        recall = overlap / len(truth)
        return clamp(2 * precision * recall / (precision + recall))


__all__ = ["F1Grader"]
