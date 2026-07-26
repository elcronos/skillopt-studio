// SkillOpt Studio — graph sidecar CLI entrypoint.
//
// Reads a skill's markdown from stdin, runs the bundled SkillForge DETERMINISTIC
// parser (buildSkillGraph + toMermaidCode), and writes a single JSON object to
// stdout:
//
//   { "mermaid": <string>, "nodes": [...], "edges": [...], "crossRefs": {...} }
//
// This wraps the existing SkillForge parser (copied verbatim under ./lib) — it
// does NOT reimplement parsing and does NOT include the llm-graph.ts augmentation
// (deterministic output only).
import { parseSkillFile } from "../lib/parser/parse-skill-file.js";
import { buildSkillGraph } from "../lib/parser/graph-builder.js";
import { toMermaidCode } from "../lib/parser/mermaid-generator.js";
import { parseMarkdownAST } from "../lib/parser/markdown-ast.js";
import {
  extractSkillInvocations,
  extractMCPRefs,
  extractToolCalls,
  extractTaskInvocations,
} from "../lib/parser/skill-references.js";

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    process.stdin.on("data", (c) => chunks.push(Buffer.from(c)));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    process.stdin.on("error", reject);
  });
}

async function main(): Promise<void> {
  const raw = await readStdin();

  // Name the skill from its frontmatter `name` (resolved inside parseSkillFile)
  // or fall back to a stable placeholder; path is informational only.
  const file = parseSkillFile("skill", "<stdin>", raw);

  // A skill body without `---` frontmatter is valid input for the studio (we
  // graph the markdown structure regardless). parseSkillFile flags this as a
  // benign "Missing frontmatter delimiters" error, but buildSkillGraph short-
  // circuits to an empty graph on ANY parseError. Clear that benign case so the
  // deterministic graph is still produced; real YAML parse failures are kept.
  if (file.parseError === "Missing frontmatter delimiters (---)") {
    file.parseError = undefined;
  }

  const graph = buildSkillGraph(file);
  const mermaid = toMermaidCode(graph);

  // Cross-references span the whole document (not just graphed sections).
  const ast = parseMarkdownAST(file.body);
  const crossRefs = {
    skills: extractSkillInvocations(ast).map((r) => r.value),
    mcp: extractMCPRefs(ast).map((r) => r.value),
    tools: extractToolCalls(ast).map((r) => r.value),
    tasks: extractTaskInvocations(ast).map((r) => r.value),
  };

  const out = {
    mermaid,
    nodes: graph.nodes,
    edges: graph.edges,
    crossRefs,
    taskGroups: graph.taskGroups ?? [],
    parseError: file.parseError ?? null,
  };

  process.stdout.write(JSON.stringify(out));
}

main().catch((err) => {
  // Emit a JSON error envelope on stderr and a non-zero exit so the Python
  // sidecar wrapper can fall back deterministically.
  const message = err instanceof Error ? err.message : String(err);
  process.stderr.write(JSON.stringify({ error: message }));
  process.exit(1);
});
