"""Fixture-replay schema probe.

``run_probe()`` replays the SYNTHETIC golden run fixture through
:func:`skillopt_studio.skillopt.outputs.parse_run_tree` and asserts the parse
produced the expected schema invariants. It is wired into server startup and
``/api/health`` (see ``main.py`` / ``api/health.py``): if the on-disk schema and
the parser ever diverge, this FAILS LOUD instead of silently degrading.

The probe is intentionally strict (it raises ``SchemaProbeError`` on divergence)
so that swapping the synthetic fixture for a real run — or a SkillOpt version
bump that changes the output schema — is caught immediately. Callers that must
not hard-fail (startup) wrap this and log.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config
from . import outputs


class SchemaProbeError(AssertionError):
    """Raised when the golden fixture does not parse to the expected schema."""


# The verified golden run path inside the fixtures tree.
GOLDEN_RUN = config.GOLDEN_RUN_DIR / "generic_qa" / "run_001"


def parse_run_tree(path: str | Path) -> outputs.RunOutputs:
    """Thin re-export so callers can ``probe.parse_run_tree`` (matches health.py
    which probes for a ``parse_run_tree`` symbol)."""
    return outputs.parse_run_tree(path)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SchemaProbeError(msg)


def run_probe(run_dir: str | Path | None = None) -> dict[str, Any]:
    """Replay the golden fixture and validate schema invariants.

    Returns a small summary dict on success. Raises :class:`SchemaProbeError`
    on divergence, or ``FileNotFoundError`` when the fixture is absent.
    """
    target = Path(run_dir) if run_dir is not None else GOLDEN_RUN
    if not target.is_dir():
        raise FileNotFoundError(f"golden run fixture not found at {target}")

    parsed = outputs.parse_run_tree(target)

    # ── Schema invariants (fail loud on divergence) ────────────────────────
    _require(bool(parsed.config), "config.yaml did not parse into a non-empty mapping")
    _require(
        parsed.config.get("env", {}).get("name") == "generic_qa"
        or parsed.config.get("env") == "generic_qa",
        "config env.name is not 'generic_qa'",
    )
    _require(bool(parsed.best_skill_path), "best_skill.md not located")
    _require(bool(parsed.best_skill_text.strip()), "best_skill.md is empty")
    _require(len(parsed.skill_versions) >= 1, "no skill_v####.md snapshots found")
    _require(len(parsed.rollouts) >= 1, "no rollout records parsed from *.jsonl")

    # Rollout records must carry the verified {id, hard, soft} shape.
    for r in parsed.rollouts:
        _require("id" in r, f"rollout missing 'id': {r}")
        _require(r.get("hard") in (0.0, 1.0), f"rollout 'hard' not 0/1: {r}")
        _require(0.0 <= float(r.get("soft", -1)) <= 1.0, f"rollout 'soft' out of [0,1]: {r}")

    # Score series + gate timeline must exist and carry an accept/reject decision.
    _require(len(parsed.score_series) >= 1, "empty score series")
    _require(len(parsed.gate_timeline) >= 1, "empty gate timeline")
    _require(
        any(g.get("accepted") is not None for g in parsed.gate_timeline),
        "gate timeline has no accept/reject decisions",
    )

    return {
        "status": "pass",
        "run_dir": str(target),
        "env_name": parsed.env_name,
        "n_skill_versions": len(parsed.skill_versions),
        "n_rollouts": len(parsed.rollouts),
        "n_score_points": len(parsed.score_series),
        "best_skill_path": parsed.best_skill_path,
        "warnings": parsed.warnings,
    }


__all__ = ["run_probe", "parse_run_tree", "SchemaProbeError", "GOLDEN_RUN"]
