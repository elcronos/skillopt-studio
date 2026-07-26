import { useEffect, useMemo, useState } from "react";
import { api, type Dataset, type DatasetCase } from "../lib/api";

interface Props {
  dataset: Dataset;
  onChange: (ds: Dataset) => void;
  onSave?: (ds: Dataset) => void;
  saving?: boolean;
  /** Skill context for AI generation — pass id or raw body. */
  skillId?: string;
  skillBody?: string;
}

function blankCase(n: number): DatasetCase {
  return { id: `case_${n}`, input: "", ground_truth: "", metadata: {} };
}

/** Edits the train/val/test case list ({id,input,ground_truth,metadata}) and
 *  the split configuration (ratio "train:valid:test" or split_dir). */
export default function DatasetEditor({
  dataset,
  onChange,
  onSave,
  saving,
  skillId,
  skillBody,
}: Props) {
  const [expanded, setExpanded] = useState<string | null>(
    dataset.cases[0]?.id ?? null,
  );

  // --- AI generation -------------------------------------------------------
  const [aiAvail, setAiAvail] = useState<boolean | null>(null);
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiCount, setAiCount] = useState(10);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.aiAvailable().then((v) => alive && setAiAvail(v));
    return () => {
      alive = false;
    };
  }, []);

  const splitPreview = useMemo(() => {
    if (dataset.split_mode !== "ratio") return null;
    const parts = dataset.split_ratio.split(":").map((p) => Number(p.trim()));
    if (parts.length !== 3 || parts.some((p) => !Number.isFinite(p) || p < 0))
      return { invalid: true } as const;
    const sum = parts.reduce((a, b) => a + b, 0) || 1;
    const n = dataset.cases.length;
    const [tr, va, te] = parts.map((p) => Math.round((p / sum) * n));
    return { train: tr, valid: va, test: te } as const;
  }, [dataset.split_mode, dataset.split_ratio, dataset.cases.length]);

  const patch = (p: Partial<Dataset>) => onChange({ ...dataset, ...p });

  const updateCase = (i: number, p: Partial<DatasetCase>) => {
    const cases = dataset.cases.slice();
    cases[i] = { ...cases[i], ...p };
    patch({ cases });
  };
  const removeCase = (i: number) =>
    patch({ cases: dataset.cases.filter((_, idx) => idx !== i) });
  const addCase = () =>
    patch({ cases: [...dataset.cases, blankCase(dataset.cases.length + 1)] });

  const runAiGenerate = (mode: "append" | "replace") => {
    if (!aiInstruction.trim() || aiBusy) return;
    setAiBusy(true);
    setAiError(null);
    api
      .generateDataset({
        skill_id: skillId,
        skill_body: skillBody,
        instruction: aiInstruction,
        count: aiCount,
      })
      .then((res) => {
        const generated = res.cases ?? [];
        const cases =
          mode === "replace" ? generated : [...dataset.cases, ...generated];
        patch({ cases });
        setExpanded(generated[0]?.id ?? expanded);
      })
      .catch((e) => setAiError(String(e)))
      .finally(() => setAiBusy(false));
  };

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Dataset
          <small>{dataset.cases.length} cases</small>
        </div>
        <div className="row gap-sm">
          <button className="btn btn-sm btn-ghost" onClick={addCase} type="button">
            + case
          </button>
          {onSave && (
            <button
              className="btn btn-sm btn-primary"
              onClick={() => onSave(dataset)}
              disabled={saving}
              type="button"
            >
              {saving ? <span className="spin" /> : "save"}
            </button>
          )}
        </div>
      </div>

      <div className="card-pad">
        <div className="grid grid-2">
          <label className="field">
            <span className="field-label">Dataset name</span>
            <input
              className="input"
              value={dataset.name}
              onChange={(e) => patch({ name: e.target.value })}
              placeholder="my_skill_eval"
            />
          </label>
          <label className="field">
            <span className="field-label">Split mode</span>
            <select
              className="select"
              value={dataset.split_mode}
              onChange={(e) =>
                patch({ split_mode: e.target.value as Dataset["split_mode"] })
              }
            >
              <option value="ratio">ratio (deterministic)</option>
              <option value="split_dir">split_dir (pre-split)</option>
            </select>
          </label>
        </div>

        {dataset.split_mode === "ratio" && (
          <label className="field">
            <span className="field-label">Split ratio — train:valid:test</span>
            <input
              className="input"
              value={dataset.split_ratio}
              onChange={(e) => patch({ split_ratio: e.target.value })}
              placeholder="2:1:7"
            />
            {splitPreview &&
              ("invalid" in splitPreview ? (
                <span className="field-hint" style={{ color: "var(--reject)" }}>
                  Ratio must be three non-negative numbers like 2:1:7.
                </span>
              ) : (
                <div className="row gap-sm mt-sm">
                  <span className="chip chip-signal">train {splitPreview.train}</span>
                  <span className="chip chip-cyan">valid {splitPreview.valid}</span>
                  <span className="chip">test {splitPreview.test}</span>
                </div>
              ))}
          </label>
        )}
      </div>

      {aiAvail && (
        <div
          className="card-pad"
          style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}
          data-testid="ai-dataset-panel"
        >
          <span className="field-label">✨ Generate cases with AI</span>
          {aiError && (
            <div className="banner banner-danger" style={{ marginBottom: 10 }}>
              <span className="banner-icon">✕</span>
              <div>AI generation failed: {aiError}</div>
            </div>
          )}
          <div className="row gap-sm" style={{ alignItems: "flex-end" }}>
            <label className="field" style={{ flex: 1, marginBottom: 0 }}>
              <span className="field-hint" style={{ margin: 0 }}>
                Instruction
              </span>
              <input
                className="input"
                value={aiInstruction}
                disabled={aiBusy}
                placeholder="e.g. tricky edge cases that stress the skill's rules"
                onChange={(e) => setAiInstruction(e.target.value)}
              />
            </label>
            <label className="field" style={{ width: 90, marginBottom: 0 }}>
              <span className="field-hint" style={{ margin: 0 }}>
                Count
              </span>
              <input
                className="input"
                type="number"
                min={1}
                max={50}
                value={aiCount}
                disabled={aiBusy}
                onChange={(e) =>
                  setAiCount(
                    Math.max(1, Math.min(50, Number(e.target.value) || 1)),
                  )
                }
              />
            </label>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={aiBusy || !aiInstruction.trim()}
              onClick={() => runAiGenerate("append")}
            >
              {aiBusy ? <span className="spin" /> : "✨ generate (append)"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={aiBusy || !aiInstruction.trim()}
              onClick={() => runAiGenerate("replace")}
            >
              replace
            </button>
          </div>
          <span className="field-hint" style={{ marginTop: 6 }}>
            Drafts cases into the list below — review and edit before saving.
          </span>
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--border)" }}>
        {dataset.cases.length === 0 ? (
          <div className="empty">No cases yet — add one to begin.</div>
        ) : (
          dataset.cases.map((c, i) => {
            const open = expanded === c.id;
            return (
              <div
                key={c.id + i}
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <div
                  className="row between"
                  style={{ padding: "12px 18px", cursor: "pointer" }}
                  onClick={() => setExpanded(open ? null : c.id)}
                >
                  <span className="row gap-sm" style={{ minWidth: 0 }}>
                    <span className="chip mono">{c.id || "(no id)"}</span>
                    <span
                      className="faint mono"
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        maxWidth: 360,
                      }}
                    >
                      {c.input || "(empty input)"}
                    </span>
                  </span>
                  <span className="faint mono">{open ? "▾" : "▸"}</span>
                </div>
                {open && (
                  <div className="card-pad" style={{ paddingTop: 0 }}>
                    <div className="grid grid-2">
                      <label className="field">
                        <span className="field-label">id</span>
                        <input
                          className="input"
                          value={c.id}
                          onChange={(e) => updateCase(i, { id: e.target.value })}
                        />
                      </label>
                      <label className="field">
                        <span className="field-label">ground_truth</span>
                        <input
                          className="input"
                          value={c.ground_truth ?? ""}
                          onChange={(e) =>
                            updateCase(i, { ground_truth: e.target.value })
                          }
                        />
                      </label>
                    </div>
                    <label className="field">
                      <span className="field-label">input</span>
                      <textarea
                        className="textarea"
                        value={c.input}
                        onChange={(e) =>
                          updateCase(i, { input: e.target.value })
                        }
                      />
                    </label>
                    <label className="field">
                      <span className="field-label">metadata (JSON)</span>
                      <textarea
                        className="textarea"
                        style={{ minHeight: 60 }}
                        defaultValue={JSON.stringify(c.metadata ?? {}, null, 2)}
                        onBlur={(e) => {
                          try {
                            updateCase(i, {
                              metadata: JSON.parse(e.target.value || "{}"),
                            });
                          } catch {
                            /* keep prior value on parse error */
                          }
                        }}
                      />
                    </label>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => removeCase(i)}
                      type="button"
                    >
                      remove case
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
