import { describe, expect, it } from "vitest";
import {
  bodyLines,
  flattenNodes,
  nodeById,
  nodeForLine,
} from "../lib/skillNodes";
import type { GraphNode } from "../lib/api";

// Mirrors the real /api/skills/{id}/graph shape: a node with nested subSteps,
// each carrying a 1-based inclusive sourceRange into the SKILL.md body.
const NODES: GraphNode[] = [
  { id: "root", label: "skill", kind: "step", sourceRange: { start: 1, end: 80 } },
  {
    id: "sec-a",
    label: "Section A",
    kind: "step",
    sourceRange: { start: 10, end: 40 },
    subSteps: [
      {
        id: "sec-a-1",
        label: "A.1",
        kind: "step",
        parentId: "sec-a",
        sourceRange: { start: 12, end: 20 },
      },
    ],
  },
];

describe("skillNodes", () => {
  it("flattens the subStep forest in document order with depth", () => {
    const flat = flattenNodes(NODES);
    expect(flat.map((n) => n.id)).toEqual(["root", "sec-a", "sec-a-1"]);
    expect(flat.find((n) => n.id === "sec-a-1")?.depth).toBe(1);
    expect(flat.find((n) => n.id === "sec-a-1")?.parentId).toBe("sec-a");
  });

  it("maps a line to the SMALLEST containing node (most specific section)", () => {
    const flat = flattenNodes(NODES);
    // line 15 is inside root(1-80), sec-a(10-40) AND sec-a-1(12-20) -> pick the
    // tightest span.
    expect(nodeForLine(flat, 15)?.id).toBe("sec-a-1");
    // line 30 is inside root + sec-a only.
    expect(nodeForLine(flat, 30)?.id).toBe("sec-a");
    // line 5 is only inside root.
    expect(nodeForLine(flat, 5)?.id).toBe("root");
    // line beyond all ranges -> null.
    expect(nodeForLine(flat, 999)).toBeNull();
  });

  it("resolves a node by id and splits a body into lines (no trailing blank)", () => {
    const flat = flattenNodes(NODES);
    expect(nodeById(flat, "sec-a")?.label).toBe("Section A");
    expect(nodeById(flat, "missing")).toBeNull();
    expect(bodyLines("a\nb\nc\n")).toEqual(["a", "b", "c"]);
    expect(bodyLines("")).toEqual([]);
  });
});
