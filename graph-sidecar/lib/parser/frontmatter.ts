// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/frontmatter.ts
// copied from SkillForge, deterministic parser, do not edit in place
import matter from "gray-matter";
import type { FrontMatter } from "../types/skill.js";

export interface FrontmatterResult {
  data: FrontMatter;
  content: string;
  error?: string;
}

export function extractFrontmatter(raw: string): FrontmatterResult {
  if (!raw.trimStart().startsWith("---")) {
    return {
      data: {},
      content: raw,
      error: "Missing frontmatter delimiters (---)",
    };
  }
  try {
    const parsed = matter(raw);
    return {
      data: (parsed.data ?? {}) as FrontMatter,
      content: parsed.content,
    };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return {
      data: {},
      content: raw,
      error: `Frontmatter parse error: ${message}`,
    };
  }
}
