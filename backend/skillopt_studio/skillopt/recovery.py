"""Crash recovery + partial-run reconstruction.

When a SkillOpt subprocess crashes (non-zero exit, killed, or raises mid-run),
the run is marked ``failed`` and we salvage whatever the run directory already
contains: the per-step score series so far, the gate timeline, the last skill
snapshot, and the step at which it failed. This lets the UI show "failed at step
N" with the partial evolution curve rather than nothing.

Built on the same defensive parser as the results API (``outputs.parse_run_tree``)
so recovery and normal reconciliation agree on the schema.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from . import outputs


def _last_step_from_skills(run_dir: Path) -> Optional[int]:
    """Return the highest ``skill_v####.md`` step number present, if any."""
    skills = run_dir / "skills"
    if not skills.is_dir():
        return None
    steps = []
    for p in skills.glob("skill_v*.md"):
        m = outputs._SKILL_VERSION_RE.search(p.name)
        if m:
            steps.append(int(m.group(1)))
    return max(steps) if steps else None


def reconstruct_partial(
    run_dir: str | os.PathLike,
    error_message: str = "",
    exit_code: Optional[int] = None,
) -> dict[str, Any]:
    """Parse a crashed run dir and return a partial-results summary.

    Never raises: a totally empty/garbage dir yields ``failed_at_step=None`` and
    empty series. The returned dict is JSON-serializable for the runs API.
    """
    run_path = Path(run_dir)
    summary: dict[str, Any] = {
        "status": "failed",
        "run_dir": str(run_path),
        "failed_at_step": None,
        "error_message": error_message,
        "exit_code": exit_code,
        "score_series": [],
        "gate_timeline": [],
        "last_skill_path": None,
        "best_skill_path": None,
        "n_rollouts": 0,
        "warnings": [],
    }

    if not run_path.is_dir():
        summary["warnings"].append(f"run dir absent: {run_path}")
        return summary

    try:
        parsed = outputs.parse_run_tree(run_path)
    except Exception as exc:  # noqa: BLE001 - hard divergence on a partial dir is OK
        summary["warnings"].append(f"parser could not interpret run dir: {exc}")
        summary["failed_at_step"] = _last_step_from_skills(run_path)
        return summary

    summary["score_series"] = [p.to_dict() for p in parsed.score_series]
    summary["gate_timeline"] = parsed.gate_timeline
    summary["best_skill_path"] = parsed.best_skill_path
    summary["n_rollouts"] = len(parsed.rollouts)
    summary["warnings"].extend(parsed.warnings)

    # "failed at step N" = the last step that produced a record/snapshot.
    last_recorded = None
    if parsed.score_series:
        last_recorded = max(p.step for p in parsed.score_series)
    skill_step = _last_step_from_skills(run_path)
    if skill_step is not None:
        last_recorded = max(last_recorded, skill_step) if last_recorded is not None else skill_step
    summary["failed_at_step"] = last_recorded

    if skill_step is not None:
        cand = run_path / "skills" / f"skill_v{skill_step:04d}.md"
        if cand.is_file():
            summary["last_skill_path"] = str(cand)

    return summary


def classify_exit(exit_code: Optional[int], cancelled: bool) -> str:
    """Map a process outcome to a run status string."""
    if cancelled:
        return "cancelled"
    if exit_code == 0:
        return "completed"
    return "failed"


__all__ = ["reconstruct_partial", "classify_exit"]
