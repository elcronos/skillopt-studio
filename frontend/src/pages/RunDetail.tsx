import { useEffect, useReducer, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api,
  subscribeRun,
  type ConnState,
  type ScorePoint,
  type SkillVersion,
  type SSEEvent,
  type TrainRun,
  type TrainRunStatus,
} from "../lib/api";
import EvolutionGraph, { STAGES } from "../components/EvolutionGraph";
import VersionDiff from "../components/VersionDiff";
import RunConsole, { type ConsoleLine } from "../components/RunConsole";

interface LiveState {
  series: ScorePoint[];
  lines: ConsoleLine[];
  stage: number | null;
  step: number | null;
  totalSteps: number | null;
  epoch: number | null;
  totalEpochs: number | null;
  failure: { message: string; recoverable: boolean } | null;
  status: TrainRunStatus | null;
  bestSkillPath: string | null;
  finalTestScore: number | null;
}

const initial: LiveState = {
  series: [],
  lines: [],
  stage: null,
  step: null,
  totalSteps: null,
  epoch: null,
  totalEpochs: null,
  failure: null,
  status: null,
  bestSkillPath: null,
  finalTestScore: null,
};

function stageIndex(stage: string): number | null {
  const lower = stage.toLowerCase();
  const i = STAGES.findIndex((s) => lower.includes(s));
  return i === -1 ? null : i + 1;
}

function reduce(state: LiveState, ev: SSEEvent): LiveState {
  switch (ev.type) {
    case "step": {
      // Upsert the score point for this step.
      const series = state.series.slice();
      const at = series.findIndex((p) => p.step === ev.step);
      const point: ScorePoint = {
        step: ev.step,
        epoch: state.epoch ?? 0,
        train_score: ev.train_score ?? (at >= 0 ? series[at].train_score : null),
        sel_score: ev.sel_score ?? (at >= 0 ? series[at].sel_score : null),
        accepted: ev.accepted ?? (at >= 0 ? series[at].accepted : null),
      };
      if (at >= 0) series[at] = point;
      else series.push(point);
      return {
        ...state,
        series,
        step: ev.step,
        totalSteps: ev.total_steps ?? state.totalSteps,
        stage: null,
      };
    }
    case "epoch":
      return {
        ...state,
        epoch: ev.epoch,
        totalEpochs: ev.total_epochs ?? state.totalEpochs,
      };
    case "stage":
      return {
        ...state,
        stage: ev.index ?? stageIndex(ev.stage),
        lines: [
          ...state.lines,
          { text: `▸ ${ev.index ?? ""}/${ev.total ?? 6} ${ev.stage}`, kind: "stage" },
        ],
      };
    case "error":
      return {
        ...state,
        failure: { message: ev.message, recoverable: ev.recoverable },
        lines: [...state.lines, { text: `✕ ${ev.message}`, kind: "err" }],
      };
    case "done":
      return {
        ...state,
        status: ev.status,
        bestSkillPath: ev.best_skill_path ?? null,
        finalTestScore: ev.final_test_score ?? null,
        stage: null,
        lines: [
          ...state.lines,
          { text: `— run ${ev.status} —`, kind: "muted" },
        ],
      };
    case "log":
      return {
        ...state,
        lines: [...state.lines, { text: ev.line, kind: "log" }],
      };
    default:
      return state;
  }
}

const STATUS_CLASS: Record<string, string> = {
  running: "status-running",
  completed: "status-completed",
  failed: "status-failed",
  cancelled: "status-cancelled",
  pending: "status-pending",
};

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const nav = useNavigate();
  const [live, dispatch] = useReducer(reduce, initial);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [run, setRun] = useState<TrainRun | null>(null);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const linesRef = useRef(0);

  // Fetch run metadata + any persisted score series / versions (replay).
  useEffect(() => {
    if (!runId) return;
    api.getRun(runId).then(setRun).catch(() => setRun(null));
    api.listVersions(runId).then(setVersions).catch(() => setVersions([]));
    api
      .getScores(runId)
      .then((pts) => pts.forEach((p) => dispatch({ type: "step", ...p })))
      .catch(() => {
        /* no persisted scores yet */
      });
  }, [runId]);

  // Subscribe to the live SSE stream with auto-reconnect.
  useEffect(() => {
    if (!runId) return;
    const dispose = subscribeRun(runId, {
      onEvent: dispatch,
      onStateChange: setConn,
      onDone: () => {
        // Refresh versions on completion to pick up best_skill.md.
        api.listVersions(runId).then(setVersions).catch(() => {});
        api.getRun(runId).then(setRun).catch(() => {});
      },
    });
    return dispose;
  }, [runId]);

  linesRef.current = live.lines.length;
  const status = live.status ?? run?.status ?? "pending";

  if (!runId) return null;

  return (
    <div className="fade-up">
      <div className="page-head">
        <div>
          <div className="eyebrow">live telemetry</div>
          <h1 className="page-title">Run {runId}</h1>
          <p className="page-sub">
            {run
              ? `${run.skill_id} · ${run.dataset_name} · ${run.model_config.backend}`
              : "loading run metadata…"}
          </p>
        </div>
        <div className="row gap-sm row-wrap">
          <span className={`status-pill ${STATUS_CLASS[status] ?? ""}`}>
            {status}
          </span>
          {status === "running" && (
            <button
              className="btn btn-danger btn-sm"
              type="button"
              onClick={() =>
                api
                  .cancelRun(runId)
                  .then((res) =>
                    setRun((prev) =>
                      prev ? { ...prev, status: res.status } : prev,
                    ),
                  )
                  .catch(() => {})
              }
            >
              ■ cancel
            </button>
          )}
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            onClick={() => nav("/train")}
          >
            new run
          </button>
        </div>
      </div>

      {live.bestSkillPath && (
        <div className="banner banner-info" style={{ marginBottom: 18 }}>
          <span className="banner-icon">★</span>
          <div>
            Best skill written to <span className="mono">{live.bestSkillPath}</span>
            {live.finalTestScore != null && (
              <>
                {" "}
                · held-out test score{" "}
                <strong>{live.finalTestScore.toFixed(3)}</strong>
              </>
            )}
          </div>
        </div>
      )}

      {/* HERO */}
      <EvolutionGraph
        series={live.series}
        currentStage={live.stage}
        connState={conn}
        totalSteps={live.totalSteps}
        epoch={live.epoch}
        totalEpochs={live.totalEpochs}
      />

      <div className="grid grid-2 mt">
        <VersionDiff versions={versions} />
        <RunConsole lines={live.lines} failure={live.failure} />
      </div>
    </div>
  );
}
