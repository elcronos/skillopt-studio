import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Skill, type SkillGraph } from "../lib/api";
import MermaidGraph from "./MermaidGraph";
import SkillInspector from "./SkillInspector";

interface Props {
  skill: Skill | null;
}

type Tab = "graph" | "source" | "split";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "graph", label: "Graph", hint: "structure flow" },
  { key: "source", label: "Source", hint: "SKILL.md + line map" },
  { key: "split", label: "Split", hint: "graph + source" },
];

/**
 * Right-hand inspector for a selected skill, organised as a tabbed surface:
 *   Graph  — the interactive structure graph (pan/zoom + cross-ref chips)
 *   Source — the SKILL.md body with a line-number gutter + section outline
 *   Split  — graph on top, source below (stacks on narrow screens)
 *
 * The panel owns `selectedNodeId`, the single source of truth shared between
 * the graph and the inspector. Because the graph endpoint gives every node a
 * 1-based `sourceRange` and the mermaid node id equals the optimizer node id,
 * the link is exact in both directions:
 *   node click   → highlight + scroll the node's line band in the source
 *   line/outline → select the smallest node whose range contains that line
 */
export default function StructureGraphPanel({ skill }: Props) {
  const [graph, setGraph] = useState<SkillGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState<Tab>("split");

  // Linked-selection state (shared across graph + source).
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Bumped on every (re)selection so the source flash replays even when the id
  // is unchanged.
  const [flashKey, setFlashKey] = useState(0);

  // Cache of fully-hydrated skill bodies, keyed by skill id, so re-selecting a
  // skill is instant and we never refetch a body we already have.
  const bodyCache = useRef<Map<string, string>>(new Map());
  const [bodySkill, setBodySkill] = useState<Skill | null>(null);

  // --- Graph fetch -----------------------------------------------------------
  useEffect(() => {
    setSelectedNodeId(null);
    if (!skill) {
      setGraph(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setMissing(false);
    api
      .getSkillGraph(skill.id)
      .then((g) => alive && setGraph(g))
      .catch((e) => {
        if (!alive) return;
        if (e instanceof ApiError && e.isNotFound) setMissing(true);
        else setGraph({ error: String(e), rawMarkdown: skill.body });
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [skill]);

  // --- Body fetch (for the Source tab), cached per skill ---------------------
  useEffect(() => {
    if (!skill) {
      setBodySkill(null);
      return;
    }
    const cached = bodyCache.current.get(skill.id) ?? skill.body;
    if (cached) {
      setBodySkill({ ...skill, body: cached });
      bodyCache.current.set(skill.id, cached);
      return;
    }
    let alive = true;
    setBodySkill({ ...skill, body: undefined }); // show "loading source…"
    api
      .getSkill(skill.id)
      .then((full) => {
        if (!alive) return;
        if (full.body) bodyCache.current.set(skill.id, full.body);
        setBodySkill(full);
      })
      .catch(() => {
        if (alive) setBodySkill({ ...skill, body: skill.body });
      });
    return () => {
      alive = false;
    };
  }, [skill]);

  // Selecting a node: store id, bump flash, and (if hidden) reveal the source
  // so the highlight is actually visible — the "linked" reveal behavior.
  const selectNode = (id: string | null) => {
    setSelectedNodeId(id);
    setFlashKey((k) => k + 1);
    if (id && tab === "graph") setTab("split");
  };

  const graphHasNodes = !!graph?.nodes?.length;

  return (
    <section className="card fade-up inspector-card">
      <div className="card-head inspector-head">
        <div className="card-title">
          Skill inspector
          <small>{skill ? skill.id : "select a skill"}</small>
        </div>
        <div className="row gap-sm">
          {skill && (
            <div
              className="inspector-tabs"
              role="tablist"
              aria-label="inspector view"
            >
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.key}
                  className={`inspector-tab${tab === t.key ? " is-active" : ""}`}
                  onClick={() => setTab(t.key)}
                  title={t.hint}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
          {skill && (
            <a
              className="chip"
              href={`/runs?skill=${encodeURIComponent(skill.id)}`}
            >
              optimize →
            </a>
          )}
        </div>
      </div>

      {!skill ? (
        <div className="empty">
          <div className="big">◧</div>
          Pick a skill on the left to inspect its structure.
        </div>
      ) : (
        <div className={`inspector-body view-${tab}`}>
          {(tab === "graph" || tab === "split") && (
            <div className="inspector-pane inspector-pane-graph">
              {loading ? (
                <div className="empty">
                  <span className="spin" /> &nbsp; building graph…
                </div>
              ) : missing ? (
                <div className="card-pad">
                  <div className="banner banner-info">
                    <span className="banner-icon">ℹ</span>
                    <div>
                      The graph endpoint is unavailable (404). The backend graph
                      sidecar may still be coming online — read the source on the
                      Source tab.
                    </div>
                  </div>
                </div>
              ) : (
                <MermaidGraph
                  graph={graph ?? undefined}
                  selected={selectedNodeId}
                  onSelect={selectNode}
                />
              )}
            </div>
          )}

          {(tab === "source" || tab === "split") && (
            <div className="inspector-pane inspector-pane-source">
              <SkillInspector
                skill={bodySkill}
                nodes={graphHasNodes ? graph?.nodes : undefined}
                selectedNodeId={selectedNodeId}
                onSelectNode={selectNode}
                flashKey={flashKey}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
