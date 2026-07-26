import { useCallback, useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";
import type { SkillGraph } from "../lib/api";
import { usePanZoom } from "../lib/usePanZoom";

/** CSS.escape with a conservative fallback for older runtimes / jsdom. */
function cssEscape(id: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(id);
  }
  return id.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

let initialized = false;
function ensureInit() {
  if (initialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "dark",
    securityLevel: "loose",
    fontFamily: "JetBrains Mono, monospace",
    // Larger base font + generous spacing so nodes are legible once fitted.
    fontSize: 16,
    flowchart: {
      useMaxWidth: false, // we control sizing via the pan/zoom transform
      htmlLabels: true,
      nodeSpacing: 45,
      rankSpacing: 60,
      padding: 14,
      curve: "basis",
    },
    themeVariables: {
      primaryColor: "#131820",
      primaryBorderColor: "#313c4c",
      primaryTextColor: "#e6edf3",
      lineColor: "#5e6b78",
      background: "#07090c",
    },
  });
  initialized = true;
}

/**
 * SkillForge emits a left-to-right flowchart (`flowchart LR`), which becomes an
 * extremely wide, short strip for skills with many sequential steps — so
 * fit-to-view collapses it to ~14% in a tall panel. Re-orient to top-down so the
 * graph fills a vertical inspector panel and stays readable. Only the leading
 * direction token is rewritten; node/edge syntax is untouched.
 */
function reorientTopDown(src: string): string {
  if (!src) return src;
  return src.replace(
    /^(\s*(?:flowchart|graph))\s+(LR|RL)\b/im,
    "$1 TB",
  );
}

interface Props {
  /** Either pass a graph payload from /api/skills/{id}/graph, or a raw mermaid string. */
  graph?: SkillGraph;
  mermaidText?: string;
  /** Cross-reference chips per node: forward (→N) / back (←M). */
  crossRefs?: Record<string, { forward: number; back: number }>;
  /** Controlled selection: when provided, the highlighted node is driven by the
   *  parent (so the Inspector and graph stay in lock-step). Falls back to local
   *  uncontrolled state when omitted. */
  selected?: string | null;
  /** Fires with the clicked node id (or null when clicking empty canvas). */
  onSelect?: (id: string | null) => void;
}

/**
 * Renders a mermaid diagram inside an interactive pan/zoom viewport with:
 *  - wheel-to-zoom (toward cursor), click-drag to pan, fit-to-view on render
 *  - an on-screen control cluster (zoom in / out / fit) + live zoom % readout
 *  - click-to-highlight (clicking a node dims the rest, click empty to reset) —
 *    drags are distinguished from clicks by a movement threshold so panning
 *    never swallows a node selection
 *  - cross-reference chips (→N forward / ←M back) summarising edges
 *  - graceful raw-text fallback banner when the backend returns {error, rawMarkdown}
 */
export default function MermaidGraph({
  graph,
  mermaidText,
  crossRefs,
  selected,
  onSelect,
}: Props) {
  const source = reorientTopDown(graph?.mermaid ?? mermaidText ?? "");
  const refs = crossRefs ?? graph?.crossRefs;
  const hasError = !!graph?.error;
  const rawId = useId().replace(/[:]/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [renderError, setRenderError] = useState<string | null>(null);

  // Controlled-or-uncontrolled selection. When `onSelect` is supplied the parent
  // owns the value; otherwise we keep it locally (legacy standalone behavior).
  const isControlled = onSelect !== undefined;
  const [localActive, setLocalActive] = useState<string | null>(null);
  const active = isControlled ? selected ?? null : localActive;
  const select = useCallback(
    (next: string | null) => {
      if (isControlled) onSelect?.(next);
      else setLocalActive(next);
    },
    [isControlled, onSelect],
  );

  useEffect(() => {
    if (!source || hasError) {
      setSvg("");
      return;
    }
    ensureInit();
    let cancelled = false;
    setRenderError(null);
    mermaid
      .render(`mmd-${rawId}`, source)
      .then(({ svg }) => {
        if (!cancelled) setSvg(svg);
      })
      .catch((e: unknown) => {
        if (!cancelled) setRenderError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [source, hasError, rawId]);

  // Natural size of the rendered SVG, read from its viewBox / bbox, used to
  // fit the graph into the viewport.
  const getContentSize = useCallback(() => {
    const svgEl = contentRef.current?.querySelector("svg");
    if (!svgEl) return null;
    const vb = svgEl.viewBox?.baseVal;
    if (vb && vb.width > 0 && vb.height > 0) {
      return { width: vb.width, height: vb.height };
    }
    try {
      const box = (svgEl as SVGSVGElement).getBBox();
      if (box.width > 0 && box.height > 0) {
        return { width: box.width, height: box.height };
      }
    } catch {
      /* getBBox throws if not laid out (jsdom) */
    }
    const r = svgEl.getBoundingClientRect();
    return r.width > 0 && r.height > 0
      ? { width: r.width, height: r.height }
      : null;
  }, []);

  const pz = usePanZoom(getContentSize, [svg]);
  const { zoomIn, zoomOut, reset, transform, transformStyle, isPanning } = pz;

  // Click-to-highlight: delegate clicks on rendered SVG nodes. A click that
  // ended a pan gesture is ignored so dragging never changes the selection.
  // Hit area is enlarged (see .node-hit) and the selected node gets a
  // persistent ring (.selected) on top of the transient .highlit glow.
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const nodes = Array.from(el.querySelectorAll<SVGGElement>("g.node"));
    nodes.forEach((n) => {
      const isSel = active != null && n.id === active;
      n.classList.toggle("dimmed", active != null && !isSel);
      n.classList.toggle("highlit", isSel);
      n.classList.toggle("selected", isSel);
      n.style.cursor = "pointer";
      // Enlarge the clickable surface: a transparent rect behind each node's
      // shape so the whole label box (incl. padding) is a comfortable target.
      if (!n.querySelector(".node-hit")) {
        try {
          const bb = n.getBBox();
          const pad = 6;
          const rect = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "rect",
          );
          rect.setAttribute("class", "node-hit");
          rect.setAttribute("x", String(bb.x - pad));
          rect.setAttribute("y", String(bb.y - pad));
          rect.setAttribute("width", String(bb.width + pad * 2));
          rect.setAttribute("height", String(bb.height + pad * 2));
          rect.setAttribute("fill", "transparent");
          n.insertBefore(rect, n.firstChild);
        } catch {
          /* getBBox throws if not laid out (jsdom) */
        }
      }
    });
    const onClick = (e: Event) => {
      if (pz.wasDragging()) return;
      const target = (e.target as Element)?.closest("g.node") as SVGGElement | null;
      if (!target) {
        select(null);
        return;
      }
      select(active === target.id ? null : target.id);
    };
    el.addEventListener("click", onClick);
    return () => el.removeEventListener("click", onClick);
  }, [svg, active, pz, select]);

  // When the selection is driven externally (e.g. a node clicked in the
  // Inspector), bring that node into view inside the graph viewport.
  useEffect(() => {
    if (!active) return;
    const el = contentRef.current;
    const vp = pz.viewportRef.current;
    if (!el || !vp) return;
    const node = el.querySelector<SVGGElement>(`g.node#${cssEscape(active)}`);
    if (!node) return;
    let box: DOMRect;
    try {
      box = node.getBoundingClientRect();
    } catch {
      return;
    }
    const vpRect = vp.getBoundingClientRect();
    // If the node is already comfortably inside the viewport, leave the camera be.
    const inside =
      box.left >= vpRect.left &&
      box.right <= vpRect.right &&
      box.top >= vpRect.top &&
      box.bottom <= vpRect.bottom;
    if (inside) return;
    const dx = vpRect.left + vpRect.width / 2 - (box.left + box.width / 2);
    const dy = vpRect.top + vpRect.height / 2 - (box.top + box.height / 2);
    pz.panBy(dx, dy);
  }, [active, svg, pz]);

  // --- Raw-text fallback banner (backend couldn't extract a graph) ---
  if (hasError) {
    return (
      <div className="card-pad">
        <div className="banner banner-warn" role="alert">
          <span className="banner-icon">⚠</span>
          <div>
            <strong>Graph extraction failed.</strong> {graph?.error}. Showing the
            raw skill markdown instead.
          </div>
        </div>
        <pre
          className="console"
          style={{ height: "auto", maxHeight: 420, marginTop: 14 }}
        >
          {graph?.rawMarkdown ?? "(no markdown provided)"}
        </pre>
      </div>
    );
  }

  if (!source) {
    return (
      <div className="empty">
        <div className="big">◇</div>
        No graph available for this skill.
      </div>
    );
  }

  if (renderError) {
    return (
      <div className="card-pad">
        <div className="banner banner-danger" role="alert">
          <span className="banner-icon">✕</span>
          <div>
            <strong>Could not render mermaid.</strong> {renderError}
          </div>
        </div>
        <pre className="console" style={{ height: "auto", marginTop: 14 }}>
          {source}
        </pre>
      </div>
    );
  }

  const zoomPct = Math.round(transform.k * 100);

  return (
    <div ref={containerRef}>
      {refs && Object.keys(refs).length > 0 && (
        <div
          className="row row-wrap gap-sm"
          style={{ padding: "12px 18px 0" }}
          aria-label="cross references"
        >
          {Object.entries(refs).map(([key, val]) => {
            // Two payload shapes are supported:
            //  - categorized (live API): { skills: string[], mcp: [], tools: [], tasks: [] }
            //  - legacy per-node:        { <nodeId>: { forward, back } }
            if (Array.isArray(val)) {
              const items = val.map((v) =>
                typeof v === "string" ? v : (v?.name ?? v?.id ?? String(v)),
              );
              if (items.length === 0) return null; // hide empty categories
              return (
                <span
                  key={key}
                  className="chip chip-cyan"
                  title={`${key}: ${items.join(", ")}`}
                >
                  {key} <span className="faint">{items.length}</span>
                </span>
              );
            }
            const { forward = 0, back = 0 } = val ?? {};
            return (
              <button
                key={key}
                type="button"
                className="chip chip-cyan"
                onClick={() => select(active === key ? null : key)}
                aria-pressed={active === key}
                title={`${key}: ${forward} outgoing, ${back} incoming`}
              >
                {key} <span className="faint">→{forward}</span>{" "}
                <span className="faint">←{back}</span>
              </button>
            );
          })}
          {Object.values(refs).every(
            (v) => Array.isArray(v) && v.length === 0,
          ) && <span className="faint mono">no cross-references</span>}
        </div>
      )}

      <div
        ref={pz.viewportRef}
        className={`mermaid-viewport ${isPanning ? "panning" : ""}`}
      >
        <div
          ref={contentRef}
          className="mermaid-wrap"
          data-testid="mermaid-svg"
          style={{
            transform: transformStyle,
            transformOrigin: "0 0",
          }}
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: svg }}
        />

        <div className="graph-controls" role="group" aria-label="graph zoom controls">
          <span className="graph-zoom-readout mono" aria-live="polite">
            {zoomPct}%
          </span>
          <button
            type="button"
            className="graph-ctrl-btn"
            onClick={zoomIn}
            aria-label="zoom in"
            title="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            className="graph-ctrl-btn"
            onClick={zoomOut}
            aria-label="zoom out"
            title="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            className="graph-ctrl-btn graph-ctrl-fit"
            onClick={reset}
            aria-label="fit to view"
            title="Fit to view"
          >
            ⤢
          </button>
        </div>
      </div>
    </div>
  );
}
