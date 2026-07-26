/**
 * Typed client for the SkillOpt Studio backend (FastAPI on :8000, proxied at /api).
 *
 * Types mirror backend/skillopt_studio/domain.py (pydantic v2) and the SSE event
 * contract documented in SKILLOPT_INTEGRATION.md. Everything degrades gracefully:
 * the studio backend is built concurrently, so endpoints may 404. Callers receive
 * a structured ApiError and can render an empty/fallback state instead of crashing.
 */

// ---------------------------------------------------------------------------
// Domain types (mirror of domain.py)
// ---------------------------------------------------------------------------
export type ProviderName = "claude" | "codex" | "openai" | "cwd";

/** The frontend supports the full grader matrix from the integration doc,
 *  including `geval` + `recommender`, even though domain.py's enum may not list
 *  `geval` yet (backend is concurrent). Unknown values render generically. */
export type GraderType =
  | "exact"
  | "fuzzy"
  | "f1"
  | "llm_judge"
  | "geval"
  | "custom_python";

export type TrainRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Skill {
  id: string;
  name: string;
  provider: ProviderName;
  source_path: string;
  body?: string;
}

export interface SkillVersion {
  step: number;
  md_text: string;
  is_best?: boolean;
}

export interface DatasetCase {
  id: string;
  input: string;
  ground_truth?: string;
  metadata?: Record<string, unknown>;
}

export interface Dataset {
  name: string;
  cases: DatasetCase[];
  split_mode: "ratio" | "split_dir";
  split_ratio: string; // "train:valid:test", e.g. "2:1:7"
}

/** Lightweight item from GET /api/datasets (no inlined cases). */
export interface DatasetSummary {
  name: string;
  num_cases: number;
  split_mode: "ratio" | "split_dir";
  split_ratio: string;
  path: string;
}

/** G-Eval criteria — surfaced when grader type is `geval`. */
export interface GEvalCriterion {
  name: string;
  description: string;
}

export interface GraderConfig {
  type: GraderType;
  threshold: number; // 0..1, soft -> hard = soft >= threshold
  rubric?: string | null;
  judge_model?: string | null;
  custom_code?: string | null;
  custom_consent?: boolean;
  // geval-specific (optional; backend concurrent)
  criteria?: GEvalCriterion[];
  evaluation_steps?: string[];
  self_consistency?: number;
}

export interface ModelConfig {
  backend: string;
  optimizer_model: string;
  target_model: string;
  optimizer_backend?: string | null;
  target_backend?: string | null;
  endpoint?: string | null;
  api_version?: string | null;
  reasoning_effort: string;
}

/** Item returned by GET /api/models (keys are never echoed back). */
export interface ModelInfo {
  name: string;
  model: ModelConfig;
  [k: string]: unknown;
}

export interface TrainConfig {
  num_epochs: number;
  batch_size: number;
  learning_rate: number; // -> edit_budget
  lr_scheduler: "cosine" | "linear" | "constant" | "autonomous";
  analyst_workers: number;
  seed?: number;
  eval_only?: boolean;
}

/** Outputs surfaced by GET /api/runs/{id} once a run produces artifacts. */
export interface RunOutputs {
  best_skill_text?: string | null;
  skill_versions?: SkillVersion[];
  score_series?: ScorePoint[];
  final_test_score?: number | null;
  [k: string]: unknown;
}

export interface TrainRun {
  id: string;
  slug: string;
  skill_id: string;
  dataset_name: string;
  model_config: ModelConfig;
  status: TrainRunStatus;
  run_dir?: string | null;
  created_at: string;
  config_path?: string | null;
  launched?: boolean;
  error?: string | null;
  outputs?: RunOutputs | null;
  partial?: boolean;
}

/** Item shape from GET /api/runs (the `.runs` array). */
export interface RunListItem {
  id: string;
  slug: string;
  status: TrainRunStatus;
  dataset_name: string;
  run_dir?: string | null;
  created_at: string;
  error?: string | null;
}

export interface ScorePoint {
  step: number;
  epoch?: number;
  train_score?: number | null;
  sel_score?: number | null;
  accepted?: boolean | null;
}

// --- Grader recommender / estimate ----------------------------------------
export interface GraderRecommendation {
  type: GraderType;
  rationale: string;
  alternatives?: GraderType[];
}

export interface GraderEstimate {
  calls: number;
  note?: string;
}

/** Item from GET /api/graders/types — grader kinds and their availability. */
export interface GraderTypeInfo {
  type: GraderType;
  available: boolean;
  label?: string;
  description?: string;
  [k: string]: unknown;
}

/** Frontend train-request body (server resolves paths). */
export interface TrainRequest {
  slug?: string;
  skill_id: string;
  dataset_name: string;
  model_config: ModelConfig;
  grader: GraderConfig;
  train: TrainConfig;
  split_mode?: "ratio" | "split_dir";
  split_ratio?: string;
  launch?: boolean;
}

// --- Skill graph (mermaid) ------------------------------------------------
/** A 1-based, inclusive line span into the skill's SKILL.md `body`. The
 *  authoritative basis for deterministic node↔source mapping. */
export interface SourceRange {
  start: number;
  end: number;
}

/** A structure-graph node. The `id` matches both the mermaid node id (the
 *  rendered `g.node` element id) and the optimizer's internal node key, which
 *  is what makes graph↔source linking exact rather than fuzzy. */
export interface GraphNode {
  id: string;
  label: string;
  kind?: string;
  /** 1-based inclusive line span into `body`. */
  sourceRange?: SourceRange;
  /** Nested children (also carry `parentId` + their own `sourceRange`). */
  subSteps?: GraphNode[];
  parentId?: string | null;
}

export interface GraphEdge {
  from: string;
  to: string;
  kind?: string;
  provenance?: string;
}

/** /api/skills/{id}/graph returns either a renderable mermaid string + node
 *  metadata, or a fallback {error, rawMarkdown} when graph extraction failed. */
export interface SkillGraph {
  mermaid?: string;
  error?: string;
  rawMarkdown?: string;
  /** Flat/forest of structure nodes, each with a `sourceRange` into `body`. */
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  parseError?: string | null;
  /** Legacy/synthetic per-node forward/back counts used by the cross-ref chip
   *  row. The live API returns a categorized object instead (see crossRefs in
   *  the raw payload); this typed field is kept for the chip contract and is
   *  populated by callers when available. */
  crossRefs?: Record<string, { forward: number; back: number }>;
}

// --- AI generation (drafts into editors; never auto-applies) ---------------
/** Skill context for an AI-generation request: supply `skill_id` OR
 *  `skill_body`, plus a short `instruction`. */
export interface AiGenerateBase {
  skill_id?: string;
  skill_body?: string;
  instruction: string;
}
export interface GenerateDatasetRequest extends AiGenerateBase {
  count?: number;
}
export type GenerateGevalRequest = AiGenerateBase;
export type GenerateScorerRequest = AiGenerateBase;

export interface GenerateDatasetResponse {
  cases: DatasetCase[];
}
export interface GenerateGevalResponse {
  criteria: GEvalCriterion[];
  evaluation_steps: string[];
}
export interface GenerateScorerResponse {
  custom_code: string;
}

// ---------------------------------------------------------------------------
// SSE event union (stdout-authoritative live stream)
// ---------------------------------------------------------------------------
export interface StepEvent {
  type: "step";
  step: number;
  total_steps?: number | null;
  train_score?: number | null;
  sel_score?: number | null;
  accepted?: boolean | null;
}
export interface EpochEvent {
  type: "epoch";
  epoch: number;
  total_epochs?: number | null;
}
export interface StageEvent {
  type: "stage";
  step?: number | null;
  stage: string;
  index?: number | null;
  total?: number | null;
}
export interface ErrorEvent {
  type: "error";
  step?: number | null;
  message: string;
  recoverable: boolean;
}
export interface DoneEvent {
  type: "done";
  status: TrainRunStatus;
  best_skill_path?: string | null;
  final_test_score?: number | null;
}
/** Raw stdout line. The conversion pipeline tags each line with its `stage`. */
export interface LogEvent {
  type: "log";
  line: string;
  stage?: string;
  stream?: "stdout" | "stderr";
}

export type SSEEvent =
  | StepEvent
  | EpochEvent
  | StageEvent
  | ErrorEvent
  | DoneEvent
  | LogEvent;

// --- Convert to LangGraph --------------------------------------------------
export type LlmBackend = "claude_cli" | "api";

export interface ConvertRequest {
  skill_id: string;
  model?: string;
  run_parity?: boolean;
  llm_backend?: LlmBackend;
}

export interface ConversionStage {
  name: string;
  ok: boolean;
  exit_code?: number | null;
  skipped: boolean;
  tail: string[];
}

export interface ConversionArtifacts {
  skill: string;
  spec: {
    skill?: string;
    workflow_shape?: string;
    node_count: number;
    children: string[];
  } | null;
  spec_path?: string | null;
  validation: {
    checks: Record<string, boolean | null> | null;
    all_green: boolean | null;
    errors?: string[] | null;
    report_path?: string | null;
  };
  dist: {
    path: string;
    files: string[];
    has_main: boolean;
    has_requirements: boolean;
    run_command: string;
    readme_head: string;
  } | null;
  parity: Record<string, unknown> | null;
}

export interface ConversionListItem {
  id: string;
  skill_id: string;
  skill: string;
  status: TrainRunStatus;
  error?: string | null;
}

export interface Conversion extends ConversionListItem {
  stages?: ConversionStage[] | null;
  artifacts?: ConversionArtifacts | null;
  artifacts_error?: string;
}

// ---------------------------------------------------------------------------
// HTTP layer
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get isNotFound() {
    return this.status === 404;
  }
}

const BASE = "/api";

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, headers, ...rest } = init ?? {};
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  }).catch((e) => {
    throw new ApiError(0, `Network error: ${String(e)}`);
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text().catch(() => undefined);
    }
    throw new ApiError(res.status, `${res.status} ${res.statusText}`, body);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

// ---------------------------------------------------------------------------
// Endpoint surface
// ---------------------------------------------------------------------------
export interface HealthInfo {
  status: string;
  python_version?: string;
  skillopt_installed?: boolean;
  golden_fixture_ok?: boolean;
  [k: string]: unknown;
}

export const api = {
  health: () => request<HealthInfo>("/health"),

  // Skills
  listSkills: () => request<Skill[]>("/skills"),
  getSkill: (id: string) => request<Skill>(`/skills/${encodeURIComponent(id)}`),
  getSkillGraph: (id: string) =>
    request<SkillGraph>(`/skills/${encodeURIComponent(id)}/graph`),
  /** There is NO POST /skills/scan — discovery is a plain GET /skills. */
  scanSkills: () => request<Skill[]>("/skills"),

  // Datasets (CRUD)
  listDatasets: () => request<DatasetSummary[]>("/datasets"),
  getDataset: (name: string) =>
    request<Dataset>(`/datasets/${encodeURIComponent(name)}`),
  /** Create/replace a dataset: POST /api/datasets with the full body (201). */
  saveDataset: (ds: Dataset) =>
    request<Dataset>("/datasets", {
      method: "POST",
      json: {
        name: ds.name,
        cases: ds.cases,
        split_mode: ds.split_mode,
        split_ratio: ds.split_ratio,
      },
    }),
  deleteDataset: (name: string) =>
    request<{ deleted: boolean }>(`/datasets/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  // Graders
  /** Grader types + availability (e.g. whether DeepEval is installed). */
  listGraderTypes: () => request<GraderTypeInfo[]>("/graders/types"),
  recommendGrader: (datasetName: string) =>
    request<GraderRecommendation>(
      `/graders/recommend?dataset=${encodeURIComponent(datasetName)}`,
    ),
  estimateGrader: (datasetName: string) =>
    request<GraderEstimate>(
      `/graders/estimate-cost?dataset=${encodeURIComponent(datasetName)}`,
    ),
  dryRunGrader: (
    config: GraderConfig,
    prediction: string,
    ground_truth: string,
    item?: DatasetCase,
  ) =>
    request<{ soft: number; hard: number; detail?: string }>(
      "/graders/dry-run",
      { method: "POST", json: { config, prediction, ground_truth, item } },
    ),

  // Models
  listModels: () => request<ModelInfo[]>("/models"),
  /** Create a model; API keys are set here via the create body (201).
   *  There is NO separate POST /models/keys endpoint. */
  saveModel: (payload: {
    name: string;
    model: ModelConfig;
    optimizer_api_key?: string;
    target_api_key?: string;
  }) => request<ModelInfo>("/models", { method: "POST", json: payload }),
  deleteModel: (name: string) =>
    request<{ deleted: boolean }>(`/models/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  // Runs
  launchTrain: (payload: TrainRequest) =>
    request<TrainRun>("/runs/train", { method: "POST", json: payload }),
  listRuns: () =>
    request<{ runs: RunListItem[] }>("/runs").then((r) => r.runs),
  getRun: (id: string) => request<TrainRun>(`/runs/${encodeURIComponent(id)}`),
  cancelRun: (id: string) =>
    request<{ id: string; cancelled: boolean; status: TrainRunStatus }>(
      `/runs/${encodeURIComponent(id)}/cancel`,
      { method: "POST" },
    ),
  evalOnly: (id: string, split: "train" | "valid" | "test" = "test") =>
    request<TrainRun>(`/runs/${encodeURIComponent(id)}/eval`, {
      method: "POST",
      json: { split },
    }),
  listVersions: (id: string) =>
    request<{ id: string; versions: SkillVersion[] }>(
      `/runs/${encodeURIComponent(id)}/versions`,
    ).then((r) => r.versions),
  getScores: (id: string) =>
    request<{
      id: string;
      scores: ScorePoint[];
      final_test_score?: number | null;
    }>(`/runs/${encodeURIComponent(id)}/scores`).then((r) => r.scores),

  /** Build the SSE URL for a run's live event stream. */
  eventsUrl: (id: string) => `${BASE}/runs/${encodeURIComponent(id)}/events`,

  // Convert to LangGraph
  listConversions: () =>
    request<{ conversions: ConversionListItem[] }>("/conversions").then(
      (r) => r.conversions,
    ),
  createConversion: (payload: ConvertRequest) =>
    request<ConversionListItem>("/conversions", {
      method: "POST",
      json: payload,
    }),
  getConversion: (id: string) =>
    request<Conversion>(`/conversions/${encodeURIComponent(id)}`),
  cancelConversion: (id: string) =>
    request<{ id: string; cancelled: boolean; status: TrainRunStatus }>(
      `/conversions/${encodeURIComponent(id)}/cancel`,
      { method: "POST" },
    ),
  /** SSE URL for a conversion's live stage/log stream. */
  conversionEventsUrl: (id: string) =>
    `${BASE}/conversions/${encodeURIComponent(id)}/events`,

  // AI generation (drafts into editors; user reviews before save)
  /** Whether the local `claude` CLI is usable. Degrades to false on offline. */
  aiAvailable: () =>
    request<{ available: boolean }>("/ai/available")
      .then((r) => r.available)
      .catch(() => false),
  generateDataset: (req: GenerateDatasetRequest) =>
    request<GenerateDatasetResponse>("/ai/generate-dataset", {
      method: "POST",
      json: req,
    }),
  generateGeval: (req: GenerateGevalRequest) =>
    request<GenerateGevalResponse>("/ai/generate-geval", {
      method: "POST",
      json: req,
    }),
  generateScorer: (req: GenerateScorerRequest) =>
    request<GenerateScorerResponse>("/ai/generate-scorer", {
      method: "POST",
      json: req,
    }),
};

// ---------------------------------------------------------------------------
// SSE wrapper with auto-reconnect (powers the live EvolutionGraph)
// ---------------------------------------------------------------------------
export type ConnState = "connecting" | "open" | "reconnecting" | "closed";

export interface RunStreamHandlers {
  onEvent?: (e: SSEEvent) => void;
  onStateChange?: (s: ConnState) => void;
  /** Server sent a terminal `done` event; the stream self-closes after this. */
  onDone?: (e: DoneEvent) => void;
}

/**
 * Subscribe to a run's SSE stream with exponential-backoff auto-reconnect.
 *
 * The backend emits named SSE events (event: step / epoch / stage / error /
 * done / log) per the contract. We register listeners for each known name and
 * also handle the default `message` event for forward-compat. A terminal
 * `done` event closes the stream and suppresses reconnect.
 *
 * Returns a disposer that permanently closes the connection.
 */
export function subscribeRun(
  runId: string,
  handlers: RunStreamHandlers,
): () => void {
  return subscribeStream(api.eventsUrl(runId), handlers);
}

/** Subscribe to a conversion's SSE stream (stage/log/error/done). */
export function subscribeConversion(
  convId: string,
  handlers: RunStreamHandlers,
): () => void {
  return subscribeStream(api.conversionEventsUrl(convId), handlers);
}

/** Generic SSE subscriber with exponential-backoff auto-reconnect. Powers both
 *  the training run stream and the conversion stream. */
export function subscribeStream(
  url: string,
  handlers: RunStreamHandlers,
): () => void {
  let es: EventSource | null = null;
  let closed = false;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const setState = (s: ConnState) => handlers.onStateChange?.(s);

  const dispatch = (raw: string) => {
    let parsed: SSEEvent;
    try {
      parsed = JSON.parse(raw) as SSEEvent;
    } catch {
      // Treat unparseable data as a raw log line so nothing is silently lost.
      parsed = { type: "log", line: raw };
    }
    handlers.onEvent?.(parsed);
    if (parsed.type === "done") {
      handlers.onDone?.(parsed);
      // Server signalled completion: stop reconnecting.
      closed = true;
      es?.close();
      setState("closed");
    }
  };

  const connect = () => {
    if (closed) return;
    setState(attempt === 0 ? "connecting" : "reconnecting");
    es = new EventSource(url);

    es.onopen = () => {
      attempt = 0;
      setState("open");
    };

    // Named events from the contract.
    const named = ["step", "epoch", "stage", "error", "done", "log"];
    for (const name of named) {
      es.addEventListener(name, (ev) =>
        dispatch((ev as MessageEvent).data as string),
      );
    }
    // Default/unnamed event.
    es.onmessage = (ev) => dispatch(ev.data as string);

    es.onerror = () => {
      if (closed) return;
      es?.close();
      // Exponential backoff capped at 10s; jittered.
      attempt += 1;
      const delay = Math.min(10_000, 500 * 2 ** Math.min(attempt, 5));
      const jitter = Math.random() * 250;
      setState("reconnecting");
      reconnectTimer = setTimeout(connect, delay + jitter);
    };
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    es?.close();
    setState("closed");
  };
}
