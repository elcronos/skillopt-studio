// Source: ~/Desktop/skill-workflow/packages/shared/src/types/skill.ts
// copied from SkillForge, deterministic parser, do not edit in place
export interface FrontMatter {
  name?: string;
  description?: string;
  [key: string]: unknown;
}

export type EdgeKind =
  | "sequence"
  | "sub-skill"
  | "tool"
  | "branch"
  | "task-fanout";

export type EdgeProvenance = "inferred" | "explicit";

export type NodeKind =
  | "step"
  | "tool"
  | "sub-skill"
  | "task"
  | "task-group"
  | "branch"
  | "consequence";

export type NodeShape = "rect" | "diamond" | "round";

export interface SourceRange {
  start: number;
  end: number;
}

export type NodeSource = "parser" | "llm";

export interface SkillStep {
  id: string;
  label: string;
  kind: NodeKind;
  shape?: NodeShape;
  parentId?: string;
  collapsedSubCount?: number;
  subSteps?: SkillStep[];
  sourceRange?: SourceRange;
  /** Origin of this node — deterministic parser or LLM augmentation. */
  source?: NodeSource;
}

export interface SkillEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  provenance: EdgeProvenance;
  label?: string;
  /** True when this edge represents a loop-back / retry path (control flow). */
  loopBack?: boolean;
  /** Origin of this edge — deterministic parser or LLM augmentation. */
  source?: NodeSource;
}

export interface SkillGraph {
  nodes: SkillStep[];
  edges: SkillEdge[];
  taskGroups?: { id: string; label: string; memberIds: string[] }[];
}

export interface ImportMeta {
  origin: string;
  fetchedAt: string;
  /** Empty string when the commits API was unavailable at import time. */
  commitSha: string;
}

export interface SkillFile {
  name: string;
  path: string;
  frontMatter: FrontMatter;
  body: string;
  rawSource: string;
  parseError?: string;
  imported?: boolean;
  importMeta?: ImportMeta;
}
