// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/mermaid-generator.ts
// copied from SkillForge, deterministic parser, do not edit in place
import type { SkillEdge, SkillGraph, SkillStep } from "../types/skill.js";

function escapeLabel(s: string): string {
  return s
    .replace(/["`]/g, "'")
    .replace(/[\[\]{}()<>#]/g, " ")
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

function escapeEdgeLabel(s: string): string {
  return escapeLabel(s).replace(/\|/g, "/").slice(0, 40);
}

function nodeShape(n: SkillStep): string {
  const sub =
    n.collapsedSubCount && n.collapsedSubCount > 0
      ? ` [+${n.collapsedSubCount} sub-steps]`
      : "";
  const label = escapeLabel(n.label + sub);
  // Explicit shape override takes precedence over kind-based default.
  if (n.shape === "diamond") return `${n.id}{"${label}"}`;
  if (n.shape === "round") return `${n.id}(("${label}"))`;
  if (n.shape === "rect") return `${n.id}["${label}"]`;
  switch (n.kind) {
    case "tool":
      return `${n.id}[["${label}"]]`;
    case "sub-skill":
      return `${n.id}(("${label}"))`;
    case "task":
      return `${n.id}>"${label}"]`;
    case "branch":
      return `${n.id}{"${label}"}`;
    default:
      return `${n.id}["${label}"]`;
  }
}

function quotedEdgeLabel(s: string): string {
  // Always quote so labels with special chars (commas, parens) render.
  return `|"${escapeEdgeLabel(s)}"|`;
}

function edgeArrow(e: SkillEdge): string {
  const dashed = e.provenance === "inferred";
  if (e.loopBack) {
    // Thick amber arrow with leftwards-arc glyph to read as control flow.
    const lbl = e.label ? `↶ ${e.label}` : "↶ loop";
    return `==>${quotedEdgeLabel(lbl)}`;
  }
  const label = e.label ? quotedEdgeLabel(e.label) : "";
  if (e.kind === "task-fanout") {
    const lbl = e.label ? e.label : "fanout";
    return dashed ? `-.->${quotedEdgeLabel(lbl)}` : `==>${quotedEdgeLabel(lbl)}`;
  }
  if (e.kind === "branch") {
    return dashed ? `-.->${label}` : `-->${label}`;
  }
  if (e.kind === "tool") return label ? `-->${label}` : "-->";
  if (e.kind === "sub-skill") {
    const arrow = dashed ? "-.->" : "-->";
    return label ? `${arrow}${label}` : arrow;
  }
  const arrow = dashed ? "-.->" : "-->";
  return label ? `${arrow}${label}` : arrow;
}

function classFor(n: SkillStep): string {
  if (n.source === "llm") return "llmNode";
  switch (n.kind) {
    case "tool":
      return "toolNode";
    case "sub-skill":
      return "subSkillNode";
    case "task":
      return "taskNode";
    case "branch":
      return "branchNode";
    case "consequence":
      return "consequenceNode";
    default:
      return "stepNode";
  }
}

export interface MermaidOptions {
  /**
   * If provided, every node gets a `click` directive calling this global
   * function name with the node id. Caller is responsible for installing the
   * function on `window` (e.g. `__skillforgeOnNodeClick`).
   */
  clickCallback?: string;
}

export function toMermaidCode(
  graph: SkillGraph,
  options: MermaidOptions = {},
): string {
  const lines: string[] = [];
  lines.push("flowchart LR");

  const taskMembers = new Set<string>();
  if (graph.taskGroups) {
    for (const g of graph.taskGroups) {
      lines.push(`  subgraph ${g.id}["${escapeLabel(g.label)}"]`);
      lines.push("    direction TB");
      for (const m of g.memberIds) {
        const n = graph.nodes.find((x) => x.id === m);
        if (n) lines.push(`    ${nodeShape(n)}`);
        taskMembers.add(m);
      }
      lines.push("  end");
    }
  }

  for (const n of graph.nodes) {
    if (taskMembers.has(n.id)) continue;
    lines.push(`  ${nodeShape(n)}`);
  }

  const loopBackEdgeIndices: number[] = [];
  graph.edges.forEach((e, idx) => {
    lines.push(`  ${e.from} ${edgeArrow(e)} ${e.to}`);
    if (e.loopBack) loopBackEdgeIndices.push(idx);
  });

  lines.push(
    "  classDef stepNode fill:#dbeafe,stroke:#2563eb,color:#1e3a8a;",
  );
  lines.push(
    "  classDef toolNode fill:#dcfce7,stroke:#16a34a,color:#14532d;",
  );
  lines.push(
    "  classDef subSkillNode fill:#ffedd5,stroke:#ea580c,color:#7c2d12;",
  );
  lines.push(
    "  classDef taskNode fill:#fef3c7,stroke:#d97706,color:#78350f;",
  );
  lines.push(
    "  classDef branchNode fill:#fef9c3,stroke:#ca8a04,color:#713f12;",
  );
  lines.push(
    "  classDef consequenceNode fill:#e0e7ff,stroke:#4f46e5,color:#312e81;",
  );
  lines.push(
    "  classDef llmNode fill:#f3e8ff,stroke:#9333ea,color:#581c87,stroke-dasharray: 4 2;",
  );

  // LLM-only edges rendered with dotted purple stroke for visual provenance.
  const llmEdgeIndices: number[] = [];
  graph.edges.forEach((e, idx) => {
    if (e.source === "llm") llmEdgeIndices.push(idx);
  });
  for (const idx of llmEdgeIndices) {
    lines.push(
      `  linkStyle ${idx} stroke:#9333ea,stroke-width:1.5px,stroke-dasharray: 4 2,color:#581c87;`,
    );
  }

  for (const idx of loopBackEdgeIndices) {
    lines.push(
      `  linkStyle ${idx} stroke:#f59e0b,stroke-width:2px,color:#92400e;`,
    );
  }

  for (const n of graph.nodes) {
    lines.push(`  class ${n.id} ${classFor(n)};`);
  }

  if (options.clickCallback) {
    for (const n of graph.nodes) {
      lines.push(`  click ${n.id} call ${options.clickCallback}("${n.id}")`);
    }
  }

  return lines.join("\n");
}
