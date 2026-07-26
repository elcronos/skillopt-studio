"""Spawn the Node graph sidecar and parse its JSON output.

The sidecar (``graph-sidecar/graph-cli.js``) bundles the SkillForge deterministic
parser. We invoke it per request (fine for v1), pipe the skill markdown on stdin,
and parse the single JSON object it writes to stdout.

The argv is built as a list (never ``shell=True``). Any failure — Node missing,
non-zero exit, timeout, or unparseable output — raises ``GraphSidecarError`` so
callers can fall back via :func:`skillopt_studio.graph.fallback.fallback_result`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .. import config

# The bundled CLI entry produced by `npm run build` in graph-sidecar/.
_CLI_PATH = config.GRAPH_SIDECAR_DIR / "graph-cli.js"

# Per-request spawn guard. Skill markdown is small; the parser is fast.
_TIMEOUT_SECONDS = 30


class GraphSidecarError(RuntimeError):
    """Raised when the graph sidecar cannot produce a valid graph payload."""


def _node_executable() -> str:
    """Return the path to the ``node`` binary, or raise if unavailable."""
    node = shutil.which("node")
    if node is None:
        raise GraphSidecarError("node executable not found on PATH")
    return node


def build_graph(skill_markdown: str) -> dict[str, Any]:
    """Run the sidecar over ``skill_markdown`` and return its parsed JSON.

    Returns a dict shaped ``{mermaid, nodes, edges, crossRefs, taskGroups,
    parseError}``. Raises :class:`GraphSidecarError` on any failure; callers are
    expected to catch it and substitute the fallback payload.
    """
    if not _CLI_PATH.exists():
        raise GraphSidecarError(
            f"graph sidecar not built: {_CLI_PATH} missing (run `npm run build` in graph-sidecar/)"
        )

    node = _node_executable()
    argv = [node, str(_CLI_PATH)]

    try:
        proc = subprocess.run(
            argv,
            input=skill_markdown,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:  # node vanished between which() and run()
        raise GraphSidecarError(f"failed to spawn node: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GraphSidecarError(
            f"graph sidecar timed out after {_TIMEOUT_SECONDS}s"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise GraphSidecarError(
            f"graph sidecar exited {proc.returncode}: {stderr or '(no stderr)'}"
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GraphSidecarError(f"graph sidecar emitted invalid JSON: {exc}") from exc
