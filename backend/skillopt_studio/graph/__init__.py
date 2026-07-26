"""Structure-graph sidecar integration.

Wraps the Node ``graph-sidecar`` (which bundles the SkillForge deterministic
parser) so the backend can turn a skill's markdown into a Mermaid diagram plus
``nodes``/``edges``/``crossRefs``. On any sidecar failure (Node missing, non-zero
exit, unparseable output) callers get a structured fallback instead of an
exception.
"""

from __future__ import annotations

from .fallback import fallback_result
from .sidecar import GraphSidecarError, build_graph

__all__ = ["build_graph", "fallback_result", "GraphSidecarError"]
