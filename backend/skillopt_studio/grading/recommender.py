"""Grader recommender + judge-call cost estimator.

``recommend_grader`` inspects a dataset's ``ground_truth`` distribution and
suggests a grader with a one-line rationale (non-binding UI hint):

- short factual / single-token answers       → ``exact`` (or ``f1`` if multi-token)
- JSON / structured ground truth             → ``exact`` (schema/exact match)
- long free-text / multi-sentence / missing  → ``geval`` (LLM judge)

``estimate_judge_calls`` projects how many judge invocations a geval/llm_judge
run will make, so the UI can warn about cost before launch.
"""

from __future__ import annotations

import statistics
from typing import Any, Optional

from ..domain import Dataset, GraderType


def _looks_structured(text: str) -> bool:
    s = text.strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


def recommend_grader(dataset: Dataset) -> dict[str, str]:
    """Return ``{"type", "rationale"}`` recommending a grader for ``dataset``."""
    truths = [c.ground_truth for c in dataset.cases if c.ground_truth.strip()]
    if not truths:
        return {
            "type": GraderType.geval.value,
            "rationale": "No canonical ground-truth answers present; use an LLM judge (G-Eval).",
        }

    token_counts = [len(t.split()) for t in truths]
    avg_tokens = statistics.mean(token_counts)
    max_tokens = max(token_counts)
    structured_frac = sum(1 for t in truths if _looks_structured(t)) / len(truths)
    multi_sentence = sum(1 for t in truths if t.count(".") + t.count("!") + t.count("?") >= 2)

    if structured_frac >= 0.5:
        return {
            "type": GraderType.exact.value,
            "rationale": "Ground truths look like JSON/structured values; exact/schema match fits.",
        }
    if avg_tokens <= 1.5 and max_tokens <= 3:
        return {
            "type": GraderType.exact.value,
            "rationale": "Short single-token answers; exact match is reliable and free.",
        }
    if avg_tokens <= 6 and multi_sentence == 0:
        return {
            "type": GraderType.f1.value,
            "rationale": "Short factual phrases; token-overlap F1 tolerates minor wording differences.",
        }
    return {
        "type": GraderType.geval.value,
        "rationale": (
            "Long / multi-sentence free-text answers with no single canonical form; "
            "use an LLM judge (G-Eval). For verifiable answers prefer exact/f1."
        ),
    }


def estimate_judge_calls(
    dataset: Dataset,
    train_cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Estimate judge-call volume for a geval/llm_judge run.

    ``train_cfg`` may carry ``num_epochs``, ``batch_size`` (minibatch reflected
    per step), ``num_steps``, and ``self_consistency`` (N judge calls averaged).
    Estimates are rough — they bound the per-rollout judging cost so the UI can
    warn before a (potentially expensive) run.
    """
    cfg = train_cfg or {}
    num_cases = len(dataset.cases)
    num_epochs = int(cfg.get("num_epochs", 1) or 1)
    num_steps = int(cfg.get("num_steps", 0) or 0)
    self_consistency = max(1, int(cfg.get("self_consistency", 1) or 1))

    # Each step rolls out a minibatch (default: the whole train split) and judges
    # each rollout. Without an explicit step count, approximate steps ≈ epochs.
    steps = num_steps if num_steps > 0 else num_epochs
    rollouts_per_step = num_cases
    calls = steps * rollouts_per_step * self_consistency

    note = (
        f"~{calls} judge calls "
        f"({steps} steps x {rollouts_per_step} cases x {self_consistency} self-consistency). "
        "Each call hits the judge model; consider caching (geval caches by "
        "skill-version+case) and a smaller judge model to control cost."
    )
    return {"calls": calls, "note": note}


__all__ = ["recommend_grader", "estimate_judge_calls"]
