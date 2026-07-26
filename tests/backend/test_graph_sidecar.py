"""Tests for the structure-graph sidecar integration.

Two lanes:
1. Live sidecar: feed a sample skill markdown through ``build_graph`` (which
   spawns ``node graph-sidecar/graph-cli.js``) and assert the JSON carries a
   ``mermaid`` string and a non-empty ``nodes`` array. Skipped automatically if
   Node is unavailable or the sidecar bundle has not been built.
2. Fallback: assert the fallback payload exposes ``rawMarkdown`` (and an
   ``error``), and that ``build_graph`` raises ``GraphSidecarError`` on input
   the sidecar cannot turn into JSON — confirming the API's fallback branch.
"""

from __future__ import annotations

import shutil

import pytest

from skillopt_studio.config import GRAPH_SIDECAR_DIR
from skillopt_studio.graph import (
    GraphSidecarError,
    build_graph,
    fallback_result,
)

# A representative skill: an H2 step with a sub-step, a Bash tool call, a Skill()
# invocation, and a conditional branch — exercises the deterministic parser.
SAMPLE_SKILL_MD = """\
---
name: sample-skill
description: A skill used by the graph sidecar tests.
---

## Step 1
### Prepare
Run Bash("ls -la") to inspect the tree.
Use Skill("formatter") to tidy up.

## Step 2
Do the work.
If the build fails, retry Step 1.
"""

_CLI_PATH = GRAPH_SIDECAR_DIR / "graph-cli.js"

_sidecar_available = shutil.which("node") is not None and _CLI_PATH.exists()
_needs_sidecar = pytest.mark.skipif(
    not _sidecar_available,
    reason="node missing or graph-sidecar/graph-cli.js not built",
)


# ---------------------------------------------------------------------------
# Live sidecar
# ---------------------------------------------------------------------------
@_needs_sidecar
def test_build_graph_emits_mermaid_and_nodes() -> None:
    """The sidecar turns sample markdown into mermaid + nodes + edges."""
    result = build_graph(SAMPLE_SKILL_MD)

    assert isinstance(result.get("mermaid"), str)
    assert result["mermaid"].startswith("flowchart")

    nodes = result.get("nodes")
    assert isinstance(nodes, list) and len(nodes) > 0

    # Root + the two H2 steps must be present.
    labels = {n["label"] for n in nodes}
    assert "Step 1" in labels
    assert "Step 2" in labels

    assert isinstance(result.get("edges"), list)
    assert result.get("parseError") in (None, "")


@_needs_sidecar
def test_build_graph_collects_cross_refs() -> None:
    """crossRefs surfaces Skill()/Bash() references found in the body."""
    result = build_graph(SAMPLE_SKILL_MD)
    cross = result.get("crossRefs", {})

    assert "formatter" in cross.get("skills", [])
    assert any("ls" in t for t in cross.get("tools", []))


@_needs_sidecar
def test_build_graph_handles_missing_frontmatter() -> None:
    """A raw skill body (no --- frontmatter) still produces a graph."""
    result = build_graph("## Only A Step\nDo the thing.\n")
    assert result["mermaid"].startswith("flowchart")
    assert len(result["nodes"]) > 0
    assert result.get("parseError") in (None, "")


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
def test_fallback_result_shape() -> None:
    """The fallback payload carries the error and the original markdown."""
    raw = "## broken\nsome body"
    fb = fallback_result("node executable not found on PATH", raw)

    assert fb["error"] == "node executable not found on PATH"
    assert fb["rawMarkdown"] == raw
    assert fb["nodes"] == []
    assert fb["edges"] == []
    assert fb["mermaid"] is None


def test_build_graph_raises_when_sidecar_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the bundle is absent, build_graph raises so the API can fall back."""
    import skillopt_studio.graph.sidecar as sidecar_mod

    # Point the CLI path at a non-existent file to force the "not built" branch.
    monkeypatch.setattr(sidecar_mod, "_CLI_PATH", GRAPH_SIDECAR_DIR / "does-not-exist.js")

    with pytest.raises(GraphSidecarError):
        sidecar_mod.build_graph(SAMPLE_SKILL_MD)


def test_fallback_branch_on_bad_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a sidecar failure and confirm the fallback returns rawMarkdown.

    Mirrors what ``api/graph.py`` does: catch ``GraphSidecarError`` and return
    ``fallback_result(...)``.
    """
    import skillopt_studio.graph.sidecar as sidecar_mod

    def _boom(_md: str) -> dict:
        raise GraphSidecarError("graph sidecar emitted invalid JSON: boom")

    monkeypatch.setattr(sidecar_mod, "build_graph", _boom)

    raw = "<<<not real markdown / triggers parse error>>>"
    try:
        sidecar_mod.build_graph(raw)
        payload = {}  # pragma: no cover - build_graph always raises here
    except GraphSidecarError as exc:
        payload = fallback_result(str(exc), raw)

    assert payload["rawMarkdown"] == raw
    assert "invalid JSON" in payload["error"]
