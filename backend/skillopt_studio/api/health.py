"""Health endpoint with a fixture-replay schema probe.

``GET /api/health`` reports whether SkillOpt is importable, its pinned SHA, the
running Python version, and the result of replaying the golden-run fixture
through the output parser. The probe is *defensive*: missing fixture or a
not-yet-built parser report a status string rather than crashing the server.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter

from .. import config

logger = logging.getLogger("skillopt_studio.health")

router = APIRouter(prefix="/api", tags=["health"])


def _detect_skillopt() -> bool:
    """Return True when the ``skillopt`` package is importable in this venv."""
    try:
        importlib.import_module("skillopt")
        return True
    except Exception:  # noqa: BLE001 - any import failure means "not detected"
        return False


def _schema_probe() -> str:
    """Replay the golden-run fixture through the output parser.

    Returns one of ``"pass"``, ``"fail"``, or ``"absent"``. Never raises.
    """
    if not config.GOLDEN_RUN_DIR.exists():
        return "absent"
    try:
        # Import defensively: the outputs parser is built by a later feature package.
        outputs = importlib.import_module("skillopt_studio.skillopt.outputs")
    except Exception:  # noqa: BLE001
        logger.warning("schema probe skipped: skillopt.outputs not available yet")
        return "absent"

    parse = getattr(outputs, "parse_run_tree", None) or getattr(outputs, "parse_golden", None)
    if parse is None:
        logger.warning("schema probe skipped: no parse function in skillopt.outputs")
        return "absent"
    try:
        parse(config.GOLDEN_RUN_DIR)
        return "pass"
    except Exception:  # noqa: BLE001
        logger.exception("schema probe FAILED: golden fixture did not parse")
        return "fail"


@router.get("/health")
def health() -> dict[str, Any]:
    """Return server + SkillOpt + schema-probe status."""
    return {
        "status": "ok",
        "skillopt_sha": config.SKILLOPT_PINNED_SHA,
        "skillopt_detected": _detect_skillopt(),
        "schema_probe": _schema_probe(),
        "python_version": config.python_version_string(),
    }
