/**
 * Deterministic node↔source mapping for the Skill Inspector.
 *
 * The structure-graph endpoint hands back `nodes[]` where every node carries a
 * 1-based, inclusive `sourceRange: {start, end}` into the skill's SKILL.md
 * `body`, plus nested `subSteps[]`. The mermaid node id (the rendered
 * `g.node` element id) equals `node.id`. That shared id + line span is the
 * entire basis for linking — no fuzzy text matching is ever needed.
 */
import type { GraphNode } from "./api";

/** A node flattened out of the `subSteps` forest, with its nesting depth and a
 *  normalized (always-present, 1-based) line span. */
export interface FlatNode {
  id: string;
  label: string;
  kind?: string;
  depth: number;
  parentId: string | null;
  /** 1-based inclusive line span; defaults to a 1-line span if missing. */
  start: number;
  end: number;
  /** end - start + 1 — precomputed for "smallest containing span" lookups. */
  span: number;
}

/** Depth-first flatten of the node forest, preserving document order so the
 *  outline reads top-to-bottom like the source file. */
export function flattenNodes(nodes: GraphNode[] | undefined): FlatNode[] {
  const out: FlatNode[] = [];
  const walk = (ns: GraphNode[], depth: number, parentId: string | null) => {
    for (const n of ns) {
      const start = n.sourceRange?.start ?? 1;
      const end = Math.max(start, n.sourceRange?.end ?? start);
      out.push({
        id: n.id,
        label: n.label,
        kind: n.kind,
        depth,
        parentId: n.parentId ?? parentId,
        start,
        end,
        span: end - start + 1,
      });
      if (n.subSteps && n.subSteps.length) {
        walk(n.subSteps, depth + 1, n.id);
      }
    }
  };
  walk(nodes ?? [], 0, null);
  return out;
}

/** Reverse mapping: given a 1-based line, return the *smallest* node whose span
 *  contains it (the most specific section). Ties broken by latest start so the
 *  deepest/most-recent match wins. Returns null when no node covers the line. */
export function nodeForLine(
  flat: FlatNode[],
  line: number,
): FlatNode | null {
  let best: FlatNode | null = null;
  for (const n of flat) {
    if (line < n.start || line > n.end) continue;
    if (
      !best ||
      n.span < best.span ||
      (n.span === best.span && n.start > best.start)
    ) {
      best = n;
    }
  }
  return best;
}

/** Find a flat node by its id (== mermaid node id). */
export function nodeById(flat: FlatNode[], id: string | null): FlatNode | null {
  if (!id) return null;
  return flat.find((n) => n.id === id) ?? null;
}

/** Split the raw body into lines once. Trailing newline is dropped so we don't
 *  render a phantom final blank line beyond the file's real content. */
export function bodyLines(body: string | undefined | null): string[] {
  if (!body) return [];
  const text = body.endsWith("\n") ? body.slice(0, -1) : body;
  return text.split("\n");
}
