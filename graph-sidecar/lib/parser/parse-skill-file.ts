// Source: ~/Desktop/skill-workflow/packages/shared/src/parser/parse-skill-file.ts
// copied from SkillForge, deterministic parser, do not edit in place
import type { SkillFile } from "../types/skill.js";
import { extractFrontmatter } from "./frontmatter.js";

export function parseSkillFile(name: string, path: string, raw: string): SkillFile {
  const fm = extractFrontmatter(raw);
  return {
    name,
    path,
    frontMatter: fm.data,
    body: fm.content,
    rawSource: raw,
    parseError: fm.error,
  };
}
