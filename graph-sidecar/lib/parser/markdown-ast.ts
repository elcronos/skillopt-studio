// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/markdown-ast.ts
// copied from SkillForge, deterministic parser, do not edit in place
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkFrontmatter from "remark-frontmatter";
import type { Root } from "mdast";

const processor = unified().use(remarkParse).use(remarkFrontmatter, ["yaml"]);

export function parseMarkdownAST(md: string): Root {
  return processor.parse(md) as Root;
}
