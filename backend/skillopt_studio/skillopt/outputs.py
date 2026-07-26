"""Defensive parser for a SkillOpt run output tree.

Parses ``outputs/<env>/<run>/`` (or any directory matching the verified schema)
into structured, JSON-serializable data the results API and runner reconciliation
consume. Everything here is DEFENSIVE: a malformed/partial run yields whatever
could be parsed plus a list of ``warnings`` rather than raising — EXCEPT
``parse_run_tree`` raises on hard schema divergence (missing config + no skill +
no jsonl) so the fixture-replay probe can fail loud.

Verified schema (SkillOpt @ 8ebede0…, see SKILLOPT_INTEGRATION.md):
- ``config.yaml``                     — resolved run config.
- ``best_skill.md``                   — at the RUN ROOT (trainer writes here);
                                         also accept ``skills/best_skill.md``.
- ``skills/skill_v{step:04d}.md``      — per-step skill snapshots.
- ``history.json``                    — list[step_record] with ``action``
                                         (accept/accept_new_best/reject),
                                         ``selection_hard``/``selection_soft``,
                                         ``current_score``/``best_score``.
- ``**/*.jsonl``                       — rollout lines ({id,hard,soft}) and/or
                                         selection score lines ({score,step,phase}).
- ``predictions/<id>/conversation.json``
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SKILL_VERSION_RE = re.compile(r"skill_v(\d+)\.md$")
_ACCEPT_ACTIONS = {"accept", "accept_new_best"}


@dataclass
class ScorePointData:
    """Plain mirror of domain.ScorePoint (kept dependency-free so this module
    parses fixtures without importing pydantic)."""

    step: int
    epoch: int = 0
    train_score: float | None = None
    sel_score: float | None = None
    accepted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "epoch": self.epoch,
            "train_score": self.train_score,
            "sel_score": self.sel_score,
            "accepted": self.accepted,
        }


@dataclass
class RunOutputs:
    """Structured view of one parsed run directory."""

    run_dir: str
    env_name: str = ""
    run_id: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    best_skill_path: str | None = None
    best_skill_text: str = ""
    skill_versions: list[dict[str, Any]] = field(default_factory=list)  # {step, path, is_best}
    score_series: list[ScorePointData] = field(default_factory=list)
    rollouts: list[dict[str, Any]] = field(default_factory=list)
    gate_timeline: list[dict[str, Any]] = field(default_factory=list)  # {step, action, accepted, score}
    final_test_score: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "env_name": self.env_name,
            "run_id": self.run_id,
            "config": self.config,
            "best_skill_path": self.best_skill_path,
            "best_skill_text": self.best_skill_text,
            "skill_versions": self.skill_versions,
            "score_series": [p.to_dict() for p in self.score_series],
            "rollouts": self.rollouts,
            "gate_timeline": self.gate_timeline,
            "final_test_score": self.final_test_score,
            "warnings": self.warnings,
        }


# ── Low-level readers ────────────────────────────────────────────────────────

def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _read_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _iter_jsonl(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _as_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def parse_run_tree(path: str | os.PathLike) -> RunOutputs:
    """Parse a run directory into :class:`RunOutputs`.

    Raises ``ValueError`` only on hard schema divergence (the directory does not
    look like a SkillOpt run at all). Soft issues accumulate in ``warnings``.
    """
    run_dir = Path(path)
    if not run_dir.is_dir():
        raise ValueError(f"run dir does not exist or is not a directory: {run_dir}")

    out = RunOutputs(run_dir=str(run_dir))
    out.run_id = run_dir.name
    out.env_name = run_dir.parent.name if run_dir.parent else ""

    # config.yaml
    cfg_path = run_dir / "config.yaml"
    if cfg_path.is_file():
        out.config = _read_yaml(cfg_path)
        if not out.config:
            out.warnings.append("config.yaml present but did not parse as a mapping")
    else:
        out.warnings.append("config.yaml missing")

    # best_skill.md — run-root first (verified), then skills/best_skill.md.
    for candidate in (run_dir / "best_skill.md", run_dir / "skills" / "best_skill.md"):
        if candidate.is_file():
            out.best_skill_path = str(candidate)
            try:
                out.best_skill_text = candidate.read_text(encoding="utf-8")
            except OSError:
                out.warnings.append(f"best_skill unreadable at {candidate}")
            break

    # Per-step skill snapshots: skills/skill_v####.md
    skills_dir = run_dir / "skills"
    if skills_dir.is_dir():
        versions: list[dict[str, Any]] = []
        for p in sorted(skills_dir.glob("skill_v*.md")):
            m = _SKILL_VERSION_RE.search(p.name)
            if not m:
                continue
            versions.append({"step": int(m.group(1)), "path": str(p), "is_best": False})
        out.skill_versions = versions

    # history.json → gate timeline + score series (authoritative step records).
    parsed_steps = _parse_history(run_dir, out)

    # *.jsonl → rollouts + selection score lines. Reconcile/augment the series.
    _parse_jsonl_logs(run_dir, out, parsed_steps)

    # Mark the best skill version if history identifies a best_step.
    best_step = None
    hist = _read_json(run_dir / "history.json")
    if isinstance(hist, list) and hist:
        last = hist[-1]
        if isinstance(last, dict):
            best_step = last.get("best_step")
            out.final_test_score = _as_float(last.get("test_score") or last.get("test_hard"))
    if best_step is not None:
        for sv in out.skill_versions:
            sv["is_best"] = sv["step"] == best_step

    # Hard divergence: nothing recognizable at all.
    if not out.config and not out.best_skill_text and not out.skill_versions and not out.rollouts and not out.score_series:
        raise ValueError(
            f"run dir {run_dir} does not match SkillOpt schema: no config.yaml, "
            "skills, rollouts, or score series found"
        )

    out.score_series.sort(key=lambda p: p.step)
    out.gate_timeline.sort(key=lambda g: g.get("step", 0))
    return out


def _parse_history(run_dir: Path, out: RunOutputs) -> dict[int, ScorePointData]:
    """Parse ``history.json`` (or ``step_*/step_record.json``) into the gate
    timeline + a step→ScorePoint map."""
    by_step: dict[int, ScorePointData] = {}
    records: list[dict] = []

    hist = _read_json(run_dir / "history.json")
    if isinstance(hist, list):
        records = [r for r in hist if isinstance(r, dict)]
    else:
        # Fallback: scan per-step records.
        for sr in sorted(run_dir.glob("step_*/step_record.json")):
            rec = _read_json(sr)
            if isinstance(rec, dict):
                records.append(rec)

    for rec in records:
        step = rec.get("step")
        if step is None:
            continue
        step = int(step)
        action = str(rec.get("action", "") or "")
        accepted = action in _ACCEPT_ACTIONS if action else None
        sel = _as_float(rec.get("selection_hard"))
        if sel is None:
            sel = _as_float(rec.get("candidate_gate_score"))
        train = _as_float(rec.get("rollout_hard"))
        if train is None:
            train = _as_float(rec.get("current_score"))
        sp = ScorePointData(
            step=step,
            epoch=int(rec.get("epoch", 0) or 0),
            train_score=train,
            sel_score=sel,
            accepted=accepted,
        )
        by_step[step] = sp
        out.gate_timeline.append({
            "step": step,
            "epoch": sp.epoch,
            "action": action or "unknown",
            "accepted": accepted,
            "score": sel if sel is not None else _as_float(rec.get("candidate_gate_score")),
            "best_score": _as_float(rec.get("best_score")),
        })

    out.score_series.extend(by_step.values())
    return by_step


def _parse_jsonl_logs(run_dir: Path, out: RunOutputs, by_step: dict[int, ScorePointData]) -> None:
    """Scan all ``*.jsonl`` files, classifying lines into rollouts vs selection
    score lines, and augment the score series where history was absent."""
    for jp in sorted(run_dir.rglob("*.jsonl")):
        for rec in _iter_jsonl(Path(jp)):
            if not isinstance(rec, dict):
                continue
            phase = str(rec.get("phase", "") or "").lower()
            has_hard = "hard" in rec
            has_id = "id" in rec
            # Selection / gate score line.
            if "score" in rec and (phase in ("selection", "gate", "eval", "valid_seen") or not has_id):
                step = rec.get("step")
                if step is None:
                    continue
                step = int(step)
                sp = by_step.get(step)
                if sp is None:
                    sp = ScorePointData(step=step)
                    by_step[step] = sp
                    out.score_series.append(sp)
                if sp.sel_score is None:
                    sp.sel_score = _as_float(rec.get("score"))
                continue
            # Rollout line.
            if has_id and has_hard:
                out.rollouts.append({
                    "id": str(rec.get("id")),
                    "step": rec.get("step"),
                    "hard": _as_float(rec.get("hard")) or 0.0,
                    "soft": _as_float(rec.get("soft")) or 0.0,
                    "predicted_answer": rec.get("predicted_answer", ""),
                    "fail_reason": rec.get("fail_reason", ""),
                })


def find_run_dirs(env_root: str | os.PathLike) -> list[str]:
    """Return candidate run directories under ``outputs/<env>/`` (or any dir of
    runs). A run dir is one that contains config.yaml, best_skill.md, a skills/
    dir, or any *.jsonl."""
    root = Path(env_root)
    if not root.is_dir():
        return []
    found: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (
            (child / "config.yaml").is_file()
            or (child / "best_skill.md").is_file()
            or (child / "skills").is_dir()
            or any(child.glob("*.jsonl"))
        ):
            found.append(str(child))
    return found


def read_conversation(run_dir: str | os.PathLike, case_id: str) -> list[dict[str, Any]]:
    """Read ``predictions/<case_id>/conversation.json`` defensively (``[]`` if absent)."""
    p = Path(run_dir) / "predictions" / str(case_id) / "conversation.json"
    data = _read_json(p)
    return data if isinstance(data, list) else []


__all__ = [
    "RunOutputs",
    "ScorePointData",
    "parse_run_tree",
    "find_run_dirs",
    "read_conversation",
]
