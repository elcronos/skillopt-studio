import { useEffect, useMemo, useRef } from "react";
import type { Skill } from "../lib/api";
import {
  bodyLines,
  flattenNodes,
  nodeById,
  nodeForLine,
  type FlatNode,
} from "../lib/skillNodes";
import type { GraphNode } from "../lib/api";

interface Props {
  skill: Skill | null;
  /** Structure-graph nodes (with sourceRanges) for outline + line→node mapping. */
  nodes?: GraphNode[];
  /** The currently linked node id (shared with the graph). */
  selectedNodeId: string | null;
  /** Click a source line / outline entry → select the smallest containing node. */
  onSelectNode: (id: string | null) => void;
  /** Bumped each time a node is (re)clicked so a re-click re-triggers the flash
   *  even when the selected id is unchanged. */
  flashKey: number;
}

const KIND_CLASS: Record<string, string> = {
  step: "chip-signal",
  tool: "chip-accept",
  subskill: "chip-reject",
  task: "chip",
  branch: "chip-cyan",
  llm: "chip",
};

/**
 * Source viewer for a skill's SKILL.md `body`, rendered as raw monospace text
 * with a line-number gutter whose numbers align 1:1 with graph `sourceRange`s.
 *
 * Linking:
 *  - When `selectedNodeId` resolves to a node, its `start..end` lines get a lime
 *    left-border + tinted band, the band is scrolled into view, and a one-shot
 *    flash sweep plays (keyed by `flashKey`, honoring prefers-reduced-motion).
 *  - Clicking any line selects the *smallest* node whose range contains it
 *    (see nodeForLine), so the graph highlights the most specific section.
 *  - A compact outline (left rail) lists node labels; clicking one selects it.
 */
export default function SkillInspector({
  skill,
  nodes,
  selectedNodeId,
  onSelectNode,
  flashKey,
}: Props) {
  const lines = useMemo(() => bodyLines(skill?.body), [skill?.body]);
  const flat = useMemo(() => flattenNodes(nodes), [nodes]);

  const active = nodeById(flat, selectedNodeId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bandRef = useRef<HTMLDivElement>(null);

  // Scroll the active band into view (smooth unless reduced motion) whenever the
  // selection changes or is re-flashed.
  useEffect(() => {
    if (!active || !bandRef.current) return;
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    bandRef.current.scrollIntoView({
      block: "center",
      behavior: reduce ? "auto" : "smooth",
    });
  }, [active?.id, flashKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!skill) {
    return (
      <div className="empty">
        <div className="big">◧</div>
        Pick a skill on the left to read its source.
      </div>
    );
  }

  if (!skill.body) {
    return (
      <div className="empty">
        <span className="spin" /> &nbsp; loading source…
      </div>
    );
  }

  const handleLineClick = (lineNo: number) => {
    const n = nodeForLine(flat, lineNo);
    onSelectNode(n ? n.id : null);
  };

  return (
    <div className="inspector">
      {flat.length > 0 && (
        <SkillOutline
          flat={flat}
          activeId={active?.id ?? null}
          onSelect={onSelectNode}
        />
      )}

      <div className="inspector-source-wrap">
        <header className="inspector-source-head">
          <span className="mono inspector-file">
            {skill.name}
            <span className="faint">/SKILL.md</span>
          </span>
          <span className="faint mono inspector-path" title={skill.source_path}>
            {skill.source_path}
          </span>
        </header>

        <div className="inspector-source" ref={scrollRef} role="list">
          {lines.map((text, i) => {
            const lineNo = i + 1; // sourceRange is 1-based
            const inActive =
              active != null && lineNo >= active.start && lineNo <= active.end;
            const isBandStart = active != null && lineNo === active.start;
            return (
              <div
                // Re-key the band-start line on each (re)selection so the CSS
                // flash animation restarts even when start line is unchanged.
                key={isBandStart ? `${lineNo}:${flashKey}` : lineNo}
                ref={isBandStart ? bandRef : undefined}
                role="listitem"
                className={`src-line${inActive ? " src-line-hit" : ""}${
                  isBandStart ? " src-line-band-start flash" : ""
                }`}
                data-flash={isBandStart ? flashKey : undefined}
                onClick={() => handleLineClick(lineNo)}
                aria-current={inActive ? "true" : undefined}
              >
                <span className="src-gutter mono" aria-hidden="true">
                  {lineNo}
                </span>
                <code className="src-text">{text === "" ? " " : text}</code>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** Compact, indented mini-outline of node labels. Clicking jumps the source +
 *  selects the node (which the parent reflects into the graph). */
function SkillOutline({
  flat,
  activeId,
  onSelect,
}: {
  flat: FlatNode[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <nav className="inspector-outline" aria-label="skill section outline">
      <div className="inspector-outline-head mono">outline</div>
      <div className="inspector-outline-list">
        {flat.map((n) => (
          <button
            key={n.id}
            type="button"
            className={`outline-item${activeId === n.id ? " is-active" : ""}`}
            style={{ paddingLeft: 12 + n.depth * 14 }}
            onClick={() => onSelect(n.id)}
            aria-current={activeId === n.id ? "true" : undefined}
            title={`${n.label} · lines ${n.start}–${n.end}`}
          >
            <span
              className={`outline-dot chip ${
                KIND_CLASS[n.kind ?? ""] ?? "chip"
              }`}
              aria-hidden="true"
            />
            <span className="outline-label">{n.label}</span>
            <span className="outline-lines mono faint">
              {n.start}–{n.end}
            </span>
          </button>
        ))}
      </div>
    </nav>
  );
}
