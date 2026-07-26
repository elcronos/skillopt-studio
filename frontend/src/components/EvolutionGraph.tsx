import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ConnState, ScorePoint } from "../lib/api";

/** The six-stage per-step pipeline from the stdout contract. */
export const STAGES = [
  "rollout",
  "reflect",
  "aggregate",
  "select",
  "update",
  "gate",
] as const;

interface Props {
  /** Score series — one point per optimization step. Bound from SSE or backend. */
  series: ScorePoint[];
  /** Current stage index (1..6) for the live pipeline indicator. */
  currentStage?: number | null;
  /** Live SSE connection state badge. */
  connState?: ConnState;
  totalSteps?: number | null;
  epoch?: number | null;
  totalEpochs?: number | null;
}

function fmt(n: number | null | undefined) {
  return n == null ? "—" : n.toFixed(3);
}

/**
 * THE HERO. Live telemetry for an optimization run:
 *  - a score curve over steps (train_score + validation/selection score),
 *  - an accepted/rejected gate timeline (one tick per step),
 *  - a six-stage pipeline indicator reflecting the current step's stage.
 */
export default function EvolutionGraph({
  series,
  currentStage,
  connState = "closed",
  totalSteps,
  epoch,
  totalEpochs,
}: Props) {
  const data = useMemo(
    () =>
      series.map((p) => ({
        step: p.step,
        train: p.train_score ?? null,
        sel: p.sel_score ?? null,
        accepted: p.accepted,
      })),
    [series],
  );

  const best = useMemo(() => {
    let b: { step: number; v: number } | null = null;
    for (const p of series) {
      const v = p.sel_score ?? p.train_score;
      if (v != null && (b == null || v > b.v)) b = { step: p.step, v };
    }
    return b;
  }, [series]);

  const latest = series[series.length - 1];
  const accepted = series.filter((s) => s.accepted === true).length;
  const rejected = series.filter((s) => s.accepted === false).length;

  return (
    <section className="card evo fade-up" data-testid="evolution-graph">
      <div className="card-head">
        <div className="card-title">
          Evolution
          <small>live score curve · gate timeline · pipeline</small>
        </div>
        <div className="row gap-sm row-wrap">
          {epoch != null && (
            <span className="chip mono">
              epoch {epoch}
              {totalEpochs ? `/${totalEpochs}` : ""}
            </span>
          )}
          <span className={`conn-badge conn-${connState}`}>{connState}</span>
        </div>
      </div>

      <div className="card-pad evo">
        {/* Stat row */}
        <div className="evo-stat-row">
          <div className="stat">
            <div className="stat-label">step</div>
            <div className="stat-value">
              {latest?.step ?? 0}
              <span className="faint" style={{ fontSize: 14 }}>
                {totalSteps ? ` / ${totalSteps}` : ""}
              </span>
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">latest score</div>
            <div className="stat-value signal">
              {fmt(latest?.sel_score ?? latest?.train_score)}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">best (gate)</div>
            <div className="stat-value accept">{fmt(best?.v)}</div>
          </div>
          <div className="stat">
            <div className="stat-label">gate accept / reject</div>
            <div className="stat-value">
              <span style={{ color: "var(--accept)" }}>{accepted}</span>
              <span className="faint"> / </span>
              <span style={{ color: "var(--reject)" }}>{rejected}</span>
            </div>
          </div>
        </div>

        {/* Score curve */}
        <div style={{ height: 280 }} data-testid="evo-chart">
          {data.length === 0 ? (
            <div className="empty">
              <div className="big">∿</div>
              Waiting for the first step… the curve draws live as steps stream
              in.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={data}
                margin={{ top: 8, right: 14, bottom: 4, left: -16 }}
              >
                <defs>
                  <linearGradient id="trainFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#b4ff39" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#b4ff39" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="step"
                  stroke="#5e6b78"
                  tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 1]}
                  stroke="#5e6b78"
                  tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }}
                  tickLine={false}
                  width={48}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0e1218",
                    border: "1px solid rgba(255,255,255,0.14)",
                    borderRadius: 10,
                    fontFamily: "JetBrains Mono",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#9aa7b4" }}
                />
                <Area
                  type="monotone"
                  dataKey="train"
                  stroke="#b4ff39"
                  strokeWidth={2}
                  fill="url(#trainFill)"
                  connectNulls
                  dot={false}
                  name="train"
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="sel"
                  stroke="#4fd6ff"
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  connectNulls
                  dot={false}
                  name="selection (gate)"
                  isAnimationActive={false}
                />
                {best && (
                  <ReferenceDot
                    x={best.step}
                    y={best.v}
                    r={5}
                    fill="#38e8a0"
                    stroke="#07090c"
                    strokeWidth={2}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Gate timeline */}
        <div>
          <div className="stat-label" style={{ marginBottom: 6 }}>
            gate timeline · accepted vs rejected per step
          </div>
          <div className="gate-timeline" data-testid="gate-timeline">
            {series.length === 0 ? (
              <span className="faint mono">no gate decisions yet</span>
            ) : (
              series.map((p) => {
                const cls =
                  p.accepted === true
                    ? "accept"
                    : p.accepted === false
                      ? "reject"
                      : "pending";
                const v = p.sel_score ?? p.train_score ?? 0;
                return (
                  <span
                    key={p.step}
                    className={`gate-tick ${cls}`}
                    style={{ height: `${12 + v * 28}px` }}
                    title={`step ${p.step} · ${cls} · ${fmt(v)}`}
                  />
                );
              })
            )}
          </div>
        </div>

        {/* Stage pipeline */}
        <div>
          <div className="stat-label" style={{ marginBottom: 6 }}>
            stage pipeline · current step
          </div>
          <div className="pipeline" data-testid="pipeline">
            {STAGES.map((stage, i) => {
              const idx = i + 1;
              const cls =
                currentStage == null
                  ? ""
                  : idx < currentStage
                    ? "done"
                    : idx === currentStage
                      ? "active"
                      : "";
              return (
                <div key={stage} className={`stage-pill ${cls}`}>
                  <span className="stage-idx">{idx}/6</span>
                  {stage}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
