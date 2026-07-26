import type { TrainConfig } from "../lib/api";

interface Props {
  value: TrainConfig;
  onChange: (t: TrainConfig) => void;
  onLaunch: (evalOnly: boolean) => void;
  launching?: boolean;
  canLaunch?: boolean;
}

/** Epochs, batch_size, learning_rate (→ edit_budget), lr_scheduler,
 *  analyst_workers. Launches a full train run or an eval-only pass. */
export default function TrainConfigPanel({
  value,
  onChange,
  onLaunch,
  launching,
  canLaunch = true,
}: Props) {
  const patch = (p: Partial<TrainConfig>) => onChange({ ...value, ...p });
  const num = (v: string) => (v === "" ? 0 : Number(v));

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Training
          <small>optimizer.* · train.* · gradient.*</small>
        </div>
        <span className="chip mono">use_gate = true</span>
      </div>

      <div className="card-pad">
        <div className="grid grid-3">
          <label className="field">
            <span className="field-label">Epochs</span>
            <input
              className="input"
              type="number"
              min={1}
              value={value.num_epochs}
              onChange={(e) => patch({ num_epochs: num(e.target.value) })}
            />
          </label>
          <label className="field">
            <span className="field-label">Batch size</span>
            <input
              className="input"
              type="number"
              min={1}
              value={value.batch_size}
              onChange={(e) => patch({ batch_size: num(e.target.value) })}
            />
          </label>
          <label className="field">
            <span className="field-label">Analyst workers</span>
            <input
              className="input"
              type="number"
              min={1}
              value={value.analyst_workers}
              onChange={(e) => patch({ analyst_workers: num(e.target.value) })}
            />
          </label>
        </div>

        <div className="grid grid-2">
          <label className="field">
            <span className="field-label">
              Learning rate → edit budget (max edits/step)
            </span>
            <input
              className="input"
              type="number"
              min={0}
              step={0.1}
              value={value.learning_rate}
              onChange={(e) => patch({ learning_rate: num(e.target.value) })}
            />
            <span className="field-hint">
              Higher LR allows more skill edits per optimization step.
            </span>
          </label>
          <label className="field">
            <span className="field-label">LR scheduler</span>
            <select
              className="select"
              value={value.lr_scheduler}
              onChange={(e) =>
                patch({
                  lr_scheduler: e.target.value as TrainConfig["lr_scheduler"],
                })
              }
            >
              <option value="cosine">cosine</option>
              <option value="linear">linear</option>
              <option value="constant">constant</option>
              <option value="autonomous">autonomous</option>
            </select>
          </label>
        </div>

        <div
          className="row between row-wrap"
          style={{ borderTop: "1px solid var(--border)", paddingTop: 16 }}
        >
          <span className="field-hint" style={{ margin: 0 }}>
            Validation gating is mandatory in this branch.
          </span>
          <div className="row gap-sm">
            <button
              className="btn"
              type="button"
              disabled={!canLaunch || launching}
              onClick={() => onLaunch(true)}
            >
              eval-only
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={!canLaunch || launching}
              onClick={() => onLaunch(false)}
            >
              {launching ? <span className="spin" /> : "▸ launch train"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
