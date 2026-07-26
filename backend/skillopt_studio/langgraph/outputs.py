"""Defensive parser for the artifacts a LangGraph conversion produces.

Reads, when present (degrading gracefully when not):
- ``training/specs/<skill>.graphspec.json``        — the IR (shape, node count).
- ``training/reports/<skill>.json``                — the 6 validation checks.
- ``training/reports/<skill>.parity.json``         — live GEval parity scores.
- ``dist/<skill>/``                                — the runnable deliverable
  (file listing, README head, presence of main.py + requirements.txt).

Everything is best-effort: a missing/malformed file yields a null field, never
an exception, so a partially-complete or failed run still renders.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .. import config

_VALIDATION_CHECKS = (
    "schema_ok", "codegen_ok", "compile_ok", "nodes_match", "edges_cover", "smoke_ok",
)


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dist_summary(dist_dir: Path) -> Optional[dict[str, Any]]:
    if not dist_dir.is_dir():
        return None
    files = sorted(
        p.relative_to(dist_dir).as_posix()
        for p in dist_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    readme = ""
    readme_path = dist_dir / "README.md"
    if readme_path.is_file():
        try:
            readme = "\n".join(readme_path.read_text(encoding="utf-8").splitlines()[:20])
        except OSError:
            readme = ""
    return {
        "path": str(dist_dir),
        "files": files,
        "has_main": "main.py" in files,
        "has_requirements": "requirements.txt" in files,
        "run_command": f"cd {dist_dir} && pip install -r requirements.txt && python main.py",
        "readme_head": readme,
    }


def parse_conversion(skill: str, skill_dir: Optional[Path] = None) -> dict[str, Any]:
    """Parse all artifacts for *skill* under the skill-to-langgraph repo."""
    root = skill_dir or config.LANGGRAPH_SKILL_DIR
    spec_path = root / "training" / "specs" / f"{skill}.graphspec.json"
    report_path = root / "training" / "reports" / f"{skill}.json"
    parity_path = root / "training" / "reports" / f"{skill}.parity.json"
    dist_dir = root / "dist" / skill

    spec = _read_json(spec_path)
    report = _read_json(report_path)
    parity = _read_json(parity_path)

    checks = None
    all_green = None
    if report is not None:
        checks = {c: report.get(c) for c in _VALIDATION_CHECKS}
        all_green = all(bool(report.get(c)) for c in _VALIDATION_CHECKS)

    spec_summary = None
    if spec is not None:
        spec_summary = {
            "skill": spec.get("skill"),
            "workflow_shape": spec.get("workflow_shape"),
            "node_count": len(spec.get("nodes", [])),
            "children": [
                n.get("skill") for n in spec.get("nodes", [])
                if n.get("kind") == "subgraph" and n.get("skill")
            ],
        }

    return {
        "skill": skill,
        "spec": spec_summary,
        "spec_path": str(spec_path) if spec is not None else None,
        "validation": {
            "checks": checks,
            "all_green": all_green,
            "errors": (report or {}).get("errors") if report is not None else None,
            "report_path": str(report_path) if report is not None else None,
        },
        "dist": _dist_summary(dist_dir),
        "parity": parity,
    }


__all__ = ["parse_conversion"]
