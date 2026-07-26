import { useEffect, useState } from "react";
import {
  api,
  type GraderConfig as GraderCfg,
  type GraderEstimate,
  type GraderRecommendation,
  type GraderType,
} from "../lib/api";

const GRADERS: { type: GraderType; label: string; blurb: string }[] = [
  { type: "exact", label: "Exact", blurb: "String equality. Verifiable, single-token answers." },
  { type: "fuzzy", label: "Fuzzy", blurb: "Normalized similarity. Tolerant of formatting." },
  { type: "f1", label: "F1", blurb: "Token overlap. Short spans / extractive QA." },
  { type: "llm_judge", label: "LLM Judge", blurb: "Rubric-graded by a judge model." },
  { type: "geval", label: "G-Eval", blurb: "DeepEval criteria. Open-ended free-text." },
  { type: "custom_python", label: "Custom Python", blurb: "Your scoring function (sandboxed)." },
];

interface Props {
  value: GraderCfg;
  onChange: (g: GraderCfg) => void;
  datasetName?: string;
  /** Whether `geval` is available (DeepEval installed). Defaults to true. */
  gevalAvailable?: boolean;
  /** Skill context for AI generation — pass id or raw body. */
  skillId?: string;
  skillBody?: string;
}

/** Picks the grader type and surfaces:
 *  - the RECOMMENDER suggestion + rationale (/api/graders/recommend)
 *  - for geval: a criteria editor + judge-call/cost estimate (/api/graders/estimate)
 *  - for custom_python: a "runs your code locally" consent banner. */
export default function GraderConfig({
  value,
  onChange,
  datasetName,
  gevalAvailable = true,
  skillId,
  skillBody,
}: Props) {
  const [rec, setRec] = useState<GraderRecommendation | null>(null);
  const [estimate, setEstimate] = useState<GraderEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [consent, setConsent] = useState(false);

  // --- AI generation -------------------------------------------------------
  const [aiAvail, setAiAvail] = useState<boolean | null>(null);
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.aiAvailable().then((v) => alive && setAiAvail(v));
    return () => {
      alive = false;
    };
  }, []);

  const patch = (p: Partial<GraderCfg>) => onChange({ ...value, ...p });

  const genGevalCriteria = () => {
    if (!aiInstruction.trim() || aiBusy) return;
    setAiBusy(true);
    setAiError(null);
    api
      .generateGeval({
        skill_id: skillId,
        skill_body: skillBody,
        instruction: aiInstruction,
      })
      .then((res) =>
        patch({
          criteria: res.criteria ?? [],
          evaluation_steps: res.evaluation_steps ?? [],
        }),
      )
      .catch((e) => setAiError(String(e)))
      .finally(() => setAiBusy(false));
  };

  const genScorer = () => {
    if (!aiInstruction.trim() || aiBusy) return;
    setAiBusy(true);
    setAiError(null);
    api
      .generateScorer({
        skill_id: skillId,
        skill_body: skillBody,
        instruction: aiInstruction,
      })
      .then((res) => patch({ custom_code: res.custom_code }))
      .catch((e) => setAiError(String(e)))
      .finally(() => setAiBusy(false));
  };

  // Fetch recommender suggestion when the dataset changes.
  useEffect(() => {
    if (!datasetName) return;
    let alive = true;
    api
      .recommendGrader(datasetName)
      .then((r) => alive && setRec(r))
      .catch(() => alive && setRec(null));
    return () => {
      alive = false;
    };
  }, [datasetName]);

  // Estimate judge-call volume + cost for cost-bearing graders.
  useEffect(() => {
    const costly = value.type === "geval" || value.type === "llm_judge";
    if (!costly || !datasetName) {
      setEstimate(null);
      return;
    }
    let alive = true;
    setEstimating(true);
    api
      .estimateGrader(datasetName)
      .then((e) => alive && setEstimate(e))
      .catch(() => alive && setEstimate(null))
      .finally(() => alive && setEstimating(false));
    return () => {
      alive = false;
    };
  }, [value, datasetName]);

  const criteria = value.criteria ?? [];
  const updateCriterion = (i: number, p: Partial<{ name: string; description: string }>) => {
    const next = criteria.slice();
    next[i] = { ...next[i], ...p };
    patch({ criteria: next });
  };

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Grader
          <small>how each rollout is scored</small>
        </div>
        <span className="chip mono">
          hard = soft ≥ {value.threshold.toFixed(2)}
        </span>
      </div>

      <div className="card-pad">
        {/* Recommender suggestion */}
        {rec && (
          <div className="banner banner-info" style={{ marginBottom: 16 }}>
            <span className="banner-icon">★</span>
            <div>
              <strong>Recommended: {rec.type}</strong> — {rec.rationale}
              {value.type !== rec.type && (
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ marginLeft: 10 }}
                  onClick={() => patch({ type: rec.type })}
                >
                  use it
                </button>
              )}
            </div>
          </div>
        )}

        {/* Grader picker */}
        <div className="grid grid-3" style={{ gap: 10 }}>
          {GRADERS.map((g) => {
            const disabled = g.type === "geval" && !gevalAvailable;
            const selected = value.type === g.type;
            return (
              <button
                key={g.type}
                type="button"
                disabled={disabled}
                onClick={() => patch({ type: g.type })}
                className="card-pad"
                style={{
                  textAlign: "left",
                  borderRadius: "var(--r-md)",
                  border: `1px solid ${
                    selected ? "var(--signal-dim)" : "var(--border)"
                  }`,
                  background: selected
                    ? "rgba(180,255,57,0.06)"
                    : "var(--surface)",
                  cursor: disabled ? "not-allowed" : "pointer",
                  opacity: disabled ? 0.45 : 1,
                  padding: "12px 14px",
                }}
                aria-pressed={selected}
              >
                <div className="row between">
                  <strong style={{ fontSize: 13 }}>{g.label}</strong>
                  {selected && <span className="chip chip-signal">active</span>}
                </div>
                <div className="field-hint" style={{ marginTop: 6 }}>
                  {g.blurb}
                  {disabled && (
                    <em style={{ display: "block", color: "var(--reject)" }}>
                      DeepEval not installed
                    </em>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Threshold */}
        <label className="field mt">
          <span className="field-label">
            Threshold (soft → hard) · {value.threshold.toFixed(2)}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={value.threshold}
            onChange={(e) => patch({ threshold: Number(e.target.value) })}
            style={{ width: "100%", accentColor: "var(--signal)" }}
          />
        </label>

        {/* LLM judge rubric */}
        {value.type === "llm_judge" && (
          <>
            <label className="field">
              <span className="field-label">Judge model</span>
              <input
                className="input"
                value={value.judge_model ?? ""}
                placeholder="gpt-4o (independent of target/optimizer)"
                onChange={(e) => patch({ judge_model: e.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Rubric</span>
              <textarea
                className="textarea"
                value={value.rubric ?? ""}
                placeholder="Score 0..1 on faithfulness to ground_truth and clarity…"
                onChange={(e) => patch({ rubric: e.target.value })}
              />
            </label>
          </>
        )}

        {/* G-Eval criteria editor */}
        {value.type === "geval" && (
          <div className="mt">
            <div className="banner banner-info" style={{ marginBottom: 12 }}>
              <span className="banner-icon">⚙</span>
              <div>
                Judge pinned at <span className="mono">temperature 0</span>;
                results cached by (skill_version, case, judge_model) so unchanged
                outputs are not re-judged. Use for open-ended text — never for
                verifiable answers.
              </div>
            </div>
            {aiAvail && (
              <div
                className="field"
                data-testid="ai-geval-panel"
                style={{ marginBottom: 12 }}
              >
                <span className="field-label">✨ Generate criteria with AI</span>
                {aiError && (
                  <div className="banner banner-danger" style={{ marginBottom: 8 }}>
                    <span className="banner-icon">✕</span>
                    <div>{aiError}</div>
                  </div>
                )}
                <div className="row gap-sm" style={{ alignItems: "flex-end" }}>
                  <input
                    className="input"
                    style={{ flex: 1 }}
                    value={aiInstruction}
                    disabled={aiBusy}
                    placeholder="what the judge should reward / penalize"
                    onChange={(e) => setAiInstruction(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={aiBusy || !aiInstruction.trim()}
                    onClick={genGevalCriteria}
                  >
                    {aiBusy ? <span className="spin" /> : "✨ generate"}
                  </button>
                </div>
                <span className="field-hint" style={{ marginTop: 6 }}>
                  Fills the criteria + steps below — review and edit before saving.
                </span>
              </div>
            )}
            <label className="field">
              <span className="field-label">Judge model</span>
              <input
                className="input"
                value={value.judge_model ?? ""}
                placeholder="gpt-4o"
                onChange={(e) => patch({ judge_model: e.target.value })}
              />
            </label>
            <span className="field-label">Evaluation criteria</span>
            {criteria.map((c, i) => (
              <div className="grid grid-2" key={i} style={{ marginBottom: 8 }}>
                <input
                  className="input"
                  value={c.name}
                  placeholder="criterion name"
                  onChange={(e) => updateCriterion(i, { name: e.target.value })}
                />
                <div className="row gap-sm">
                  <input
                    className="input"
                    value={c.description}
                    placeholder="what to measure"
                    onChange={(e) =>
                      updateCriterion(i, { description: e.target.value })
                    }
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={() =>
                      patch({ criteria: criteria.filter((_, idx) => idx !== i) })
                    }
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() =>
                patch({ criteria: [...criteria, { name: "", description: "" }] })
              }
            >
              + criterion
            </button>
            <label className="field mt">
              <span className="field-label">
                Evaluation steps (one per line)
              </span>
              <textarea
                className="textarea"
                style={{ minHeight: 80 }}
                value={(value.evaluation_steps ?? []).join("\n")}
                placeholder={"Read the prediction.\nCompare to ground_truth.\nScore 0..1."}
                onChange={(e) =>
                  patch({
                    evaluation_steps: e.target.value
                      .split("\n")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <label className="field mt">
              <span className="field-label">Self-consistency N (avg of N judge calls)</span>
              <input
                className="input"
                type="number"
                min={1}
                max={9}
                value={value.self_consistency ?? 1}
                onChange={(e) =>
                  patch({ self_consistency: Number(e.target.value) })
                }
              />
            </label>
          </div>
        )}

        {/* custom_python consent */}
        {value.type === "custom_python" && (
          <div className="mt">
            <div className="banner banner-warn">
              <span className="banner-icon">⚠</span>
              <div>
                <strong>Runs your code locally.</strong> The scorer executes in a
                child process with rlimits, a 60s timeout, a temp cwd, and API
                keys scrubbed from its env. This is honest-mistake containment,
                not adversarial isolation. Only run code you trust.
              </div>
            </div>
            <label className="row gap-sm mt" style={{ alignItems: "center" }}>
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                style={{ accentColor: "var(--signal)" }}
              />
              <span className="field-hint" style={{ margin: 0 }}>
                I understand and consent to running this scorer locally.
              </span>
            </label>
            {aiAvail && (
              <div
                className="field mt"
                data-testid="ai-scorer-panel"
              >
                <span className="field-label">✨ Generate scorer with AI</span>
                {aiError && (
                  <div className="banner banner-danger" style={{ marginBottom: 8 }}>
                    <span className="banner-icon">✕</span>
                    <div>{aiError}</div>
                  </div>
                )}
                <div className="row gap-sm" style={{ alignItems: "flex-end" }}>
                  <input
                    className="input"
                    style={{ flex: 1 }}
                    value={aiInstruction}
                    disabled={aiBusy}
                    placeholder="how to score (e.g. F1 over tokens, JSON-field match)"
                    onChange={(e) => setAiInstruction(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={aiBusy || !aiInstruction.trim()}
                    onClick={genScorer}
                  >
                    {aiBusy ? <span className="spin" /> : "✨ generate"}
                  </button>
                </div>
                <span className="field-hint" style={{ marginTop: 6 }}>
                  Drafts into the editor below — AI code is NOT auto-run; review,
                  then consent to execute.
                </span>
              </div>
            )}
            <label className="field mt">
              <span className="field-label">
                Scorer — def score(prediction, ground_truth, item) → float[0,1]
              </span>
              <textarea
                className="textarea"
                style={{ minHeight: 160 }}
                value={value.custom_code ?? ""}
                disabled={!consent}
                placeholder={
                  "def score(prediction, ground_truth, item=None):\n    return 1.0 if ground_truth in prediction else 0.0"
                }
                onChange={(e) => patch({ custom_code: e.target.value })}
              />
            </label>
          </div>
        )}

        {/* Cost estimate for cost-bearing graders */}
        {(value.type === "geval" || value.type === "llm_judge") && (
          <div className="banner banner-info mt">
            <span className="banner-icon">$</span>
            <div>
              {estimating ? (
                <>
                  <span className="spin" /> estimating judge volume…
                </>
              ) : estimate ? (
                <>
                  <strong>~{(estimate.calls ?? 0).toLocaleString()}</strong> judge
                  calls
                  {estimate.note ? ` — ${estimate.note}` : ""}
                </>
              ) : (
                "Cost estimate unavailable (endpoint offline)."
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
