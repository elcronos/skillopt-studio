// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/skill-references.ts
// copied from SkillForge, deterministic parser, do not edit in place
import { visit } from "unist-util-visit";
import type { Root } from "mdast";

export interface RefMatch {
  value: string;
  raw: string;
}

const SKILL_RE = /Skill\(\s*["']([^"']+)["']/g;
const MCP_RE = /\b(mcp__[A-Za-z0-9_]+)/g;
const BASH_RE = /Bash\(\s*["']?([^"'),]+)/g;
// Task(subagent_type="..."), single or double quotes, allow sub_agent_type
const TASK_RE =
  /Task\([^)]*\bsub(?:_)?agent_type\s*=\s*["']([^"']+)["']/g;

function collectTextContent(ast: Root): string {
  // Concatenate text + inlineCode + code values. Skill() patterns may appear
  // inside fenced ``` blocks (instructional examples) — we still want them
  // for graph purposes but we explicitly exclude `code` nodes so quoted
  // examples in code fences do not pollute extraction. inlineCode kept since
  // skills sometimes write `Skill("foo")` inline.
  const parts: string[] = [];
  visit(ast, (node) => {
    if (node.type === "text" || node.type === "inlineCode") {
      parts.push((node as { value: string }).value);
    }
  });
  return parts.join("\n");
}

function collectAll(ast: Root): { text: string; code: string } {
  const text: string[] = [];
  const code: string[] = [];
  visit(ast, (node) => {
    if (node.type === "text" || node.type === "inlineCode") {
      text.push((node as { value: string }).value);
    } else if (node.type === "code") {
      code.push((node as { value: string }).value);
    }
  });
  return { text: text.join("\n"), code: code.join("\n") };
}

function uniqMatches(re: RegExp, hay: string): RefMatch[] {
  const seen = new Set<string>();
  const out: RefMatch[] = [];
  let m: RegExpExecArray | null;
  re.lastIndex = 0;
  while ((m = re.exec(hay)) !== null) {
    const v = m[1];
    if (!seen.has(v)) {
      seen.add(v);
      out.push({ value: v, raw: m[0] });
    }
  }
  return out;
}

export function extractSkillInvocations(ast: Root): RefMatch[] {
  const text = collectTextContent(ast);
  return uniqMatches(SKILL_RE, text);
}

export function extractMCPRefs(ast: Root): RefMatch[] {
  const text = collectTextContent(ast);
  return uniqMatches(MCP_RE, text).map((r) => ({ value: r.value, raw: r.raw }));
}

export function extractToolCalls(ast: Root): RefMatch[] {
  const text = collectTextContent(ast);
  return uniqMatches(BASH_RE, text);
}

export function extractTaskInvocations(ast: Root): RefMatch[] {
  // Task() invocations may appear in code fences (Task prompts are often
  // demonstrated in fenced blocks). Search both text and code for these.
  const { text, code } = collectAll(ast);
  const fromText = uniqMatches(TASK_RE, text);
  const fromCode = uniqMatches(TASK_RE, code);
  const seen = new Set(fromText.map((r) => r.value));
  for (const r of fromCode) if (!seen.has(r.value)) {
    seen.add(r.value);
    fromText.push(r);
  }
  return fromText;
}
