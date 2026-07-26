"""SkillOpt integration layer for SkillOpt Studio.

This subpackage wraps the installed Microsoft SkillOpt (MIT) CLI/outputs:

- ``probe``        — fixture-replay schema probe (health/startup).
- ``outputs``      — defensive parser for ``outputs/<env>/<run>/`` trees.
- ``args``         — build train.py / eval_only.py argv + env (keys via env only).
- ``configgen``    — generate ``configs/generic_qa/<slug>.yaml`` from a run request.
- ``registration`` — register the generic_qa env into the cloned SkillOpt checkout.
- ``runner``       — subprocess driver (no shell=True) parsing stdout → SSE events.
- ``recovery``     — crash handling + partial-run reconstruction.

All names are imported lazily by callers; importing this package has no side
effects and does not require SkillOpt to be installed.
"""
from __future__ import annotations

__all__ = [
    "probe",
    "outputs",
    "args",
    "configgen",
    "registration",
    "runner",
    "recovery",
]
