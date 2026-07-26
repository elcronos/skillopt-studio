# graph-sidecar

A small Node sidecar that wraps the **existing SkillForge deterministic
skill-graph parser** (it does **not** reimplement it). It reads a skill's
markdown from **stdin**, runs `buildSkillGraph` + `toMermaidCode`, and writes a
single JSON object to **stdout**:

```json
{
  "mermaid": "flowchart LR ...",
  "nodes": [ /* SkillStep[] */ ],
  "edges": [ /* SkillEdge[] */ ],
  "crossRefs": { "skills": [], "mcp": [], "tools": [], "tasks": [] },
  "taskGroups": [],
  "parseError": null
}
```

Deterministic only — the `llm-graph.ts` augmentation from SkillForge is
**intentionally excluded**.

## `lib/` — copied SkillForge parser

`lib/` is a verbatim copy of the SkillForge parser files (each carries a header
comment with its source path and a "do not edit in place" note). Source of
truth: `~/Desktop/skill-workflow/packages/shared/src/`.

| Copied file | Source |
| --- | --- |
| `lib/parser/graph-builder.ts` | `packages/shared/src/parser/graph-builder.ts` |
| `lib/parser/mermaid-generator.ts` | `packages/shared/src/parser/mermaid-generator.ts` |
| `lib/parser/skill-references.ts` | `packages/shared/src/parser/skill-references.ts` |
| `lib/parser/markdown-ast.ts` | `packages/shared/src/parser/markdown-ast.ts` |
| `lib/parser/frontmatter.ts` | `packages/shared/src/parser/frontmatter.ts` |
| `lib/parser/parse-skill-file.ts` | `packages/shared/src/parser/parse-skill-file.ts` |
| `lib/types/skill.ts` | `packages/shared/src/types/skill.ts` |

Runtime deps mirror SkillForge's `@skillforge/shared` parser deps:
`unified`, `remark-parse`, `remark-frontmatter`, `gray-matter`,
`mdast-util-to-string`, `unist-util-visit`. (`compromise` is NOT needed — it is
only used by the excluded llm-graph/rewriter code.)

## Build & run

The entry source is `src/graph-cli.ts`. It is **bundled** to a self-contained
CommonJS `graph-cli.js` with esbuild so the Python backend can spawn
`node graph-cli.js` without runtime module resolution (`gray-matter` is CJS and
relies on `require`, so the bundle targets CJS).

```bash
npm install        # one time
npm run build      # esbuild src/graph-cli.ts -> graph-cli.js (CJS bundle)
npm run typecheck  # tsc --noEmit (optional)
```

Verify:

```bash
printf '## Step 1\n### Sub\nDo X\nIf Y then Z\n' | node graph-cli.js
```

Emits valid JSON with a `mermaid` string and a populated `nodes` array
(`root`, the `## Step 1` step, and an inferred `If Y then Z` branch).

### Note on missing frontmatter

The studio passes raw skill **bodies** that may lack `---` frontmatter. The
upstream `parseSkillFile` flags that as a benign `"Missing frontmatter
delimiters (---)"` error, and `buildSkillGraph` returns an empty graph on *any*
`parseError`. The CLI wrapper (`src/graph-cli.ts`) clears only that benign case
before graphing; genuine YAML parse failures are preserved and surfaced in the
output `parseError` field.
