// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/graph-builder.ts
// copied from SkillForge, deterministic parser, do not edit in place
import { visit } from "unist-util-visit";
import { toString } from "mdast-util-to-string";
import type { Root, Heading, RootContent } from "mdast";
import type {
  SkillFile,
  SkillGraph,
  SkillStep,
  SkillEdge,
  SourceRange,
} from "../types/skill.js";
import { parseMarkdownAST } from "./markdown-ast.js";
import {
  extractSkillInvocations,
  extractToolCalls,
  extractTaskInvocations,
} from "./skill-references.js";

const META_HEADINGS = new Set(
  [
    "why this exists",
    "files",
    "references",
    "examples",
    "setup",
    "notes",
    "faq",
    "changelog",
    "credits",
  ].map((s) => s.toLowerCase()),
);

const COND_RE = /^\s*(if|when|unless)\b/i;
const ELSE_RE = /^\s*(else|otherwise)\b/i;
const LOOPBACK_RE =
  /\b(ask(?:\s+(?:again|once|for))?|retry|try\s+again|go\s+back\s+to|restart|loop|repeat|request\s+again|prompt(?:\s+for)?|wait\s+for)\b/i;

function slug(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "node"
  );
}

interface Section {
  heading: Heading;
  title: string;
  level: number;
  nodes: RootContent[];
  /** 1-based line range in body markdown (post-frontmatter). */
  bodyRange: SourceRange;
}

/**
 * Compute the line offset added by frontmatter so that AST positions (relative
 * to `body`) can be mapped back to lines in `rawSource`.
 *
 * `extractFrontmatter` strips the leading `---\n...---\n` block. Re-derive how
 * many lines that block consumed by diffing rawSource length vs body length.
 */
function frontmatterLineOffset(rawSource: string, body: string): number {
  if (!rawSource.trimStart().startsWith("---")) return 0;
  const rawLines = rawSource.split("\n").length;
  const bodyLines = body.split("\n").length;
  const offset = rawLines - bodyLines;
  return offset > 0 ? offset : 0;
}

function sectionize(ast: Root): Section[] {
  const out: Section[] = [];
  let current: (Section & { _start: number }) | null = null;
  for (const child of ast.children) {
    if (child.type === "heading" && (child.depth === 2 || child.depth === 3)) {
      if (current) {
        // Close previous: end is last node's end line, or its own start line.
        const last = current.nodes[current.nodes.length - 1];
        const end =
          last?.position?.end?.line ?? current._start;
        current.bodyRange.end = end;
      }
      const title = toString(child).trim();
      const start = child.position?.start?.line ?? 1;
      current = {
        heading: child,
        title,
        level: child.depth,
        nodes: [],
        bodyRange: { start, end: start },
        _start: start,
      };
      out.push(current);
    } else if (current) {
      current.nodes.push(child);
    }
  }
  if (current) {
    const last = current.nodes[current.nodes.length - 1];
    const end = last?.position?.end?.line ?? current._start;
    current.bodyRange.end = end;
  }
  return out;
}

function isMeta(title: string): boolean {
  return META_HEADINGS.has(title.toLowerCase().trim());
}

function sectionToSubAst(section: Section): Root {
  return { type: "root", children: section.nodes } as Root;
}

interface RawLine {
  text: string;
  /** 1-based line number relative to body. */
  line: number;
}

function sectionRawLines(section: Section): RawLine[] {
  // Walk text/inlineCode nodes and emit one entry per physical newline so that
  // soft-wrapped conditionals (`If X.\nOtherwise Y.`) are treated as separate
  // logical lines for branch detection.
  const out: RawLine[] = [];
  visit(sectionToSubAst(section), (node) => {
    if (node.type === "text" || node.type === "inlineCode") {
      const startLine = node.position?.start?.line ?? 0;
      const value = (node as { value: string }).value;
      const parts = value.split(/\n/);
      for (let i = 0; i < parts.length; i++) {
        const text = parts[i];
        if (text.trim().length === 0) continue;
        out.push({ line: startLine + i, text });
      }
    }
  });
  out.sort((a, b) => a.line - b.line);
  return out;
}

function shiftRange(
  range: SourceRange | undefined,
  offset: number,
): SourceRange | undefined {
  if (!range) return undefined;
  return { start: range.start + offset, end: range.end + offset };
}

export function buildSkillGraph(file: SkillFile): SkillGraph {
  if (file.parseError) return { nodes: [], edges: [] };

  const ast = parseMarkdownAST(file.body);
  const sections = sectionize(ast);
  const lineOffset = frontmatterLineOffset(file.rawSource, file.body);

  const nodes: SkillStep[] = [];
  const edges: SkillEdge[] = [];
  const taskGroups: { id: string; label: string; memberIds: string[] }[] = [];

  // Root node representing skill itself.
  const rootId = "root";
  const rootLabel = file.frontMatter.name || file.name;
  nodes.push({
    id: rootId,
    label: rootLabel,
    kind: "step",
    sourceRange: { start: 1, end: file.rawSource.split("\n").length },
  });

  let currentH2: SkillStep | null = null;
  let prevH2Id: string | null = null;
  let h2Count = 0;
  let collapsedCount = 0;
  const usedToolIds = new Set<string>();
  const usedSkillIds = new Set<string>();
  const usedTaskIds = new Set<string>();

  for (const section of sections) {
    if (section.level === 2) {
      if (isMeta(section.title)) {
        currentH2 = null;
        continue;
      }
      h2Count += 1;
      const id = `h2-${h2Count}-${slug(section.title)}`;
      const node: SkillStep = {
        id,
        label: section.title,
        kind: "step",
        subSteps: [],
        sourceRange: shiftRange(section.bodyRange, lineOffset),
      };
      nodes.push(node);
      edges.push({
        from: prevH2Id ?? rootId,
        to: id,
        kind: "sequence",
        provenance: prevH2Id ? "inferred" : "explicit",
      });
      prevH2Id = id;
      currentH2 = node;
      collapsedCount = 0;

      processSection(
        section,
        node,
        edges,
        nodes,
        taskGroups,
        usedToolIds,
        usedSkillIds,
        usedTaskIds,
        lineOffset,
      );
    } else if (section.level === 3) {
      if (currentH2) {
        collapsedCount += 1;
        currentH2.collapsedSubCount = collapsedCount;
        currentH2.subSteps = currentH2.subSteps ?? [];
        currentH2.subSteps.push({
          id: `${currentH2.id}-sub-${collapsedCount}`,
          label: section.title,
          kind: "step",
          parentId: currentH2.id,
          sourceRange: shiftRange(section.bodyRange, lineOffset),
        });
        processSection(
          section,
          currentH2,
          edges,
          nodes,
          taskGroups,
          usedToolIds,
          usedSkillIds,
          usedTaskIds,
          lineOffset,
        );
      }
    }
  }

  return { nodes, edges, taskGroups };
}

function truncate(s: string, n: number): string {
  const t = s.trim();
  return t.length <= n ? t : t.slice(0, n - 1) + "…";
}

function processSection(
  section: Section,
  parent: SkillStep,
  edges: SkillEdge[],
  nodes: SkillStep[],
  taskGroups: { id: string; label: string; memberIds: string[] }[],
  usedToolIds: Set<string>,
  usedSkillIds: Set<string>,
  usedTaskIds: Set<string>,
  lineOffset: number,
): void {
  const subAst = sectionToSubAst(section);
  const skills = extractSkillInvocations(subAst);
  const tools = extractToolCalls(subAst);
  const tasks = extractTaskInvocations(subAst);

  for (const s of skills) {
    const id = `skill-${slug(s.value)}`;
    if (!usedSkillIds.has(id)) {
      usedSkillIds.add(id);
      nodes.push({ id, label: s.value, kind: "sub-skill" });
    }
    edges.push({
      from: parent.id,
      to: id,
      kind: "sub-skill",
      provenance: "explicit",
    });
  }

  for (const t of tools) {
    const cmd = t.value.trim().split(/\s+/)[0] || t.value;
    const id = `tool-${slug(cmd)}`;
    if (!usedToolIds.has(id)) {
      usedToolIds.add(id);
      nodes.push({ id, label: `Bash: ${cmd}`, kind: "tool" });
    }
    edges.push({
      from: parent.id,
      to: id,
      kind: "tool",
      provenance: "explicit",
    });
  }

  if (tasks.length > 0) {
    const groupId = `taskgroup-${parent.id}`;
    const memberIds: string[] = [];
    for (const t of tasks) {
      const id = `task-${slug(t.value)}-${parent.id}`;
      if (!usedTaskIds.has(id)) {
        usedTaskIds.add(id);
        nodes.push({ id, label: `Task: ${t.value}`, kind: "task" });
      }
      memberIds.push(id);
      edges.push({
        from: parent.id,
        to: id,
        kind: "task-fanout",
        provenance: "explicit",
      });
    }
    taskGroups.push({ id: groupId, label: "Parallel tasks", memberIds });
  }

  // Conditional branches: detect first if/when/unless line, capture condition
  // text, then look ahead for the consequence (next paragraph/sub-bullet) and
  // an optional else/otherwise branch.
  const lines = sectionRawLines(section);
  let condIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (COND_RE.test(lines[i].text)) {
      condIdx = i;
      break;
    }
  }
  if (condIdx === -1) return;

  const condLine = lines[condIdx];
  const condText = truncate(condLine.text, 40);
  const branchId = `branch-${parent.id}`;
  if (nodes.find((n) => n.id === branchId)) return;

  nodes.push({
    id: branchId,
    label: condText,
    kind: "branch",
    shape: "diamond",
    sourceRange: { start: condLine.line + lineOffset, end: condLine.line + lineOffset },
  });
  edges.push({
    from: parent.id,
    to: branchId,
    kind: "branch",
    provenance: "inferred",
    label: truncate(`if ${condText.replace(/^if\s+|^when\s+|^unless\s+/i, "")}`, 30),
  });

  // Whole-condition-line loop-back check: phrases like "If X is missing, ask
  // once before starting" — the consequence ("ask once") is on the same line
  // as the condition itself.
  const inlineLoop = condLine.text.match(LOOPBACK_RE);
  if (inlineLoop) {
    const target = resolveLoopTarget(condLine.text, parent, nodes);
    if (target) {
      edges.push({
        from: branchId,
        to: target,
        kind: "branch",
        provenance: "inferred",
        label: truncate(loopEdgeLabel(inlineLoop[0]), 30),
        loopBack: true,
      });
      return;
    }
  }

  // Look for consequence line (first non-empty line after condition that
  // isn't itself another conditional or else clause).
  let consequence: RawLine | undefined;
  let elseLine: RawLine | undefined;
  for (let i = condIdx + 1; i < lines.length; i++) {
    const l = lines[i];
    if (ELSE_RE.test(l.text)) {
      elseLine = l;
      break;
    }
    if (COND_RE.test(l.text)) break;
    if (!consequence && l.text.trim().length > 0) {
      consequence = l;
    }
  }

  if (consequence) {
    const loopMatch = consequence.text.match(LOOPBACK_RE);
    if (loopMatch) {
      const target = resolveLoopTarget(consequence.text, parent, nodes);
      if (target) {
        edges.push({
          from: branchId,
          to: target,
          kind: "branch",
          provenance: "inferred",
          label: truncate(loopEdgeLabel(loopMatch[0]), 30),
          loopBack: true,
        });
      } else {
        emitForwardConsequence(branchId, consequence, lineOffset, nodes, edges);
      }
    } else {
      emitForwardConsequence(branchId, consequence, lineOffset, nodes, edges);
    }
  }

  if (elseLine) {
    const elseId = `${branchId}-else`;
    nodes.push({
      id: elseId,
      label: truncate(elseLine.text, 40),
      kind: "consequence",
      sourceRange: {
        start: elseLine.line + lineOffset,
        end: elseLine.line + lineOffset,
      },
    });
    edges.push({
      from: branchId,
      to: elseId,
      kind: "branch",
      provenance: "explicit",
      label: "else",
    });
  }
}

function emitForwardConsequence(
  branchId: string,
  consequence: RawLine,
  lineOffset: number,
  nodes: SkillStep[],
  edges: SkillEdge[],
): void {
  const consId = `${branchId}-then`;
  nodes.push({
    id: consId,
    label: truncate(consequence.text, 40),
    kind: "consequence",
    sourceRange: {
      start: consequence.line + lineOffset,
      end: consequence.line + lineOffset,
    },
  });
  edges.push({
    from: branchId,
    to: consId,
    kind: "branch",
    provenance: "explicit",
    label: "then",
  });
}

function loopEdgeLabel(verbPhrase: string): string {
  return verbPhrase.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Find the most plausible existing node to redirect a loop-back edge to.
 *
 * Strategy:
 * 1. Look for an explicit named target in the consequence text (e.g. "ask for
 *    input" → match a node whose label contains "input").
 * 2. Else fall back to the parent (nearest preceding non-meta `##` step).
 */
function resolveLoopTarget(
  text: string,
  parent: SkillStep,
  nodes: SkillStep[],
): string | undefined {
  // Extract candidate nouns: skip common verbs/connectives/articles, keep
  // word tokens >= 3 chars.
  const STOP = new Set([
    "ask",
    "retry",
    "try",
    "again",
    "go",
    "back",
    "to",
    "for",
    "the",
    "a",
    "an",
    "and",
    "or",
    "if",
    "when",
    "unless",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "any",
    "all",
    "some",
    "no",
    "not",
    "missing",
    "before",
    "after",
    "starting",
    "start",
    "once",
    "loop",
    "repeat",
    "restart",
    "request",
    "prompt",
    "wait",
    "of",
    "in",
    "on",
    "with",
    "from",
    "as",
    "by",
    "this",
    "that",
    "it",
    "its",
    "user",
    "them",
    "they",
  ]);
  const tokens = text
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, " ")
    .split(/\s+/)
    .filter((t) => t.length >= 3 && !STOP.has(t));

  // Exclude branch/consequence nodes from match candidates — they're
  // children of conditionals, not loop-back targets. Self-loops are useless.
  const candidates = nodes.filter(
    (n) => n.kind !== "branch" && n.kind !== "consequence",
  );
  for (const tok of tokens) {
    const match = candidates.find((n) => n.label.toLowerCase().includes(tok));
    if (match) return match.id;
  }

  // Fall back to parent (nearest preceding ## step).
  return parent.id !== "root" ? parent.id : undefined;
}
