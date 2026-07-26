"""Custom-Python grader (sandboxed, honest-mistake containment).

The user supplies a Python snippet (``GraderConfig.custom_code``) that defines a
function::

    def score(prediction: str, ground_truth: str, item: dict | None = None) -> float:
        ...

It is executed in a CHILD PROCESS via :mod:`grading.sandbox` (argv list, no
shell, scrubbed env, temp cwd, rlimits, 60s timeout). Running custom code
requires explicit user CONSENT (``GraderConfig.custom_consent``); without it the
grader refuses and scores 0.0 with a clear message. The returned score is always
clamped to ``[0, 1]``.

See :mod:`grading.sandbox` for the documented macOS limitations (advisory
rlimits) and the explicit non-adversarial threat model.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from ..domain import DatasetCase, GraderConfig
from .base import clamp
from .sandbox import DEFAULT_TIMEOUT_SECONDS, run_scorer

logger = logging.getLogger("skillopt_studio.grading.custom")

# Runner source: reads the JSON payload from stdin, exec's the user code in a
# fresh namespace, calls score(), and prints {"score": float} as JSON. The user
# code travels in the payload, never interpolated into this source.
_RUNNER_SOURCE = '''\
import json, sys

_payload = json.loads(sys.stdin.read())
_user_code = _payload["code"]
_ns = {"__name__": "__skillopt_scorer__"}
exec(compile(_user_code, "<custom_scorer>", "exec"), _ns)
_fn = _ns.get("score")
if not callable(_fn):
    print(json.dumps({"error": "no callable score(prediction, ground_truth, item) defined"}))
    sys.exit(1)
_result = _fn(_payload["prediction"], _payload["ground_truth"], _payload.get("item"))
print(json.dumps({"score": float(_result)}))
'''


class CustomPythonGrader:
    """Run a user-supplied scorer in the honest-mistake sandbox."""

    def __init__(self, cfg: GraderConfig, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._code = cfg.custom_code or ""
        self._consent = bool(cfg.custom_consent)
        self._timeout = timeout
        self._warned = False

    def score(
        self,
        prediction: str,
        ground_truth: str,
        *,
        item: Optional[DatasetCase] = None,
    ) -> float:
        if not self._consent:
            if not self._warned:
                logger.warning(
                    "custom_python grader requires explicit consent "
                    "(GraderConfig.custom_consent=True); scoring 0.0."
                )
                self._warned = True
            return 0.0
        if not self._code.strip():
            return 0.0

        payload = {
            "code": self._code,
            "prediction": prediction,
            "ground_truth": ground_truth,
            "item": item.model_dump() if item is not None else None,
        }

        # Write the fixed runner to a temp file; the USER code travels in the
        # JSON payload (never on argv, never interpolated into the runner source).
        fd, runner_path = tempfile.mkstemp(prefix="skillopt-runner-", suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(_RUNNER_SOURCE)
            result = run_scorer(runner_path, payload, timeout=self._timeout)
        finally:
            try:
                os.unlink(runner_path)
            except OSError:
                pass

        if not result.get("ok"):
            logger.warning("custom scorer failed: %s", result.get("error"))
            return 0.0
        return clamp(result.get("score") or 0.0)


__all__ = ["CustomPythonGrader"]
