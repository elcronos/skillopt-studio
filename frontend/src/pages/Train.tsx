import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type Dataset,
  type GraderConfig as GraderCfg,
  type ModelConfig,
  type Skill,
  type TrainConfig,
} from "../lib/api";
import SkillList from "../components/SkillList";
import DatasetEditor from "../components/DatasetEditor";
import GraderConfig from "../components/GraderConfig";
import ModelConfigForm from "../components/ModelConfigForm";
import TrainConfigPanel from "../components/TrainConfigPanel";

const STEPS = ["skill", "dataset", "grader", "model", "launch"] as const;
type StepKey = (typeof STEPS)[number];

const DEFAULT_DATASET: Dataset = {
  name: "untitled_eval",
  cases: [
    { id: "case_1", input: "", ground_truth: "", metadata: {} },
  ],
  split_mode: "ratio",
  split_ratio: "2:1:7",
};
const DEFAULT_GRADER: GraderCfg = { type: "exact", threshold: 0.5 };
const DEFAULT_MODEL: ModelConfig = {
  backend: "openai_chat",
  optimizer_model: "gpt-5.5",
  target_model: "gpt-5.5",
  reasoning_effort: "medium",
};
const DEFAULT_TRAIN: TrainConfig = {
  num_epochs: 3,
  batch_size: 8,
  learning_rate: 3,
  lr_scheduler: "cosine",
  analyst_workers: 4,
};

export default function Train() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const preselect = params.get("skill");

  const [step, setStep] = useState<StepKey>("skill");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skill, setSkill] = useState<Skill | null>(null);
  const [dataset, setDataset] = useState<Dataset>(DEFAULT_DATASET);
  const [grader, setGrader] = useState<GraderCfg>(DEFAULT_GRADER);
  const [model, setModel] = useState<ModelConfig>(DEFAULT_MODEL);
  const [train, setTrain] = useState<TrainConfig>(DEFAULT_TRAIN);
  const [launching, setLaunching] = useState(false);
  const [savingDs, setSavingDs] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listSkills()
      .then((s) => {
        setSkills(s);
        const pick = preselect ? s.find((x) => x.id === preselect) : undefined;
        if (pick) {
          setSkill(pick);
          setStep("dataset");
        }
      })
      .catch(() => setSkills([]));
  }, [preselect]);

  const idx = STEPS.indexOf(step);
  const canLaunch = useMemo(
    () => !!skill && dataset.cases.length > 0 && !!dataset.name,
    [skill, dataset],
  );

  const saveDataset = (ds: Dataset) => {
    setSavingDs(true);
    api
      .saveDataset(ds)
      .catch(() => {
        /* offline: keep local copy, allow launch attempt */
      })
      .finally(() => setSavingDs(false));
  };

  const launch = (evalOnly: boolean) => {
    if (!skill) return;
    setLaunching(true);
    setError(null);
    api
      .launchTrain({
        skill_id: skill.id,
        dataset_name: dataset.name,
        model_config: model,
        grader,
        train: { ...train, eval_only: evalOnly },
        split_mode: dataset.split_mode,
        split_ratio: dataset.split_ratio,
        launch: true,
      })
      .then((run) => nav(`/runs/${run.id}`))
      .catch((e) => setError(String(e)))
      .finally(() => setLaunching(false));
  };

  return (
    <div className="fade-up">
      <div className="page-head">
        <div>
          <div className="eyebrow">optimization pipeline</div>
          <h1 className="page-title">Train</h1>
          <p className="page-sub">
            Configure a generic_qa run end-to-end: pick the seed skill, shape the
            dataset, choose how to grade, wire up the model backend, then launch.
          </p>
        </div>
      </div>

      {/* Stepper */}
      <div className="stepper">
        {STEPS.map((s, i) => (
          <button
            key={s}
            type="button"
            className={`step-node ${
              step === s ? "active" : i < idx ? "complete" : ""
            }`}
            onClick={() => setStep(s)}
            disabled={s !== "skill" && !skill}
          >
            <span className="step-num">{i < idx ? "✓" : i + 1}</span>
            {s}
          </button>
        ))}
      </div>

      {error && (
        <div className="banner banner-danger" style={{ marginBottom: 18 }}>
          <span className="banner-icon">✕</span>
          <div>Launch failed: {error}</div>
        </div>
      )}

      {step === "skill" && (
        <section className="card">
          <div className="card-head">
            <div className="card-title">
              Pick a seed skill
              <small>this .md is what gets optimized</small>
            </div>
          </div>
          <SkillList
            skills={skills}
            selectedId={skill?.id}
            onSelect={(s) => {
              setSkill(s);
              setStep("dataset");
            }}
          />
        </section>
      )}

      {step === "dataset" && (
        <DatasetEditor
          dataset={dataset}
          onChange={setDataset}
          onSave={saveDataset}
          saving={savingDs}
          skillId={skill?.id}
          skillBody={skill?.body}
        />
      )}

      {step === "grader" && (
        <GraderConfig
          value={grader}
          onChange={setGrader}
          datasetName={dataset.name}
          skillId={skill?.id}
          skillBody={skill?.body}
        />
      )}

      {step === "model" && (
        <ModelConfigForm value={model} onChange={setModel} />
      )}

      {step === "launch" && (
        <div className="grid">
          <TrainConfigPanel
            value={train}
            onChange={setTrain}
            onLaunch={launch}
            launching={launching}
            canLaunch={canLaunch}
          />
          <section className="card">
            <div className="card-head">
              <div className="card-title">Run summary</div>
            </div>
            <div className="card-pad">
              <dl className="kv">
                <dt>skill</dt>
                <dd>{skill?.id ?? "—"}</dd>
                <dt>dataset</dt>
                <dd>
                  {dataset.name} · {dataset.cases.length} cases ·{" "}
                  {dataset.split_mode === "ratio"
                    ? dataset.split_ratio
                    : "split_dir"}
                </dd>
                <dt>grader</dt>
                <dd>
                  {grader.type} · hard≥{grader.threshold.toFixed(2)}
                </dd>
                <dt>backend</dt>
                <dd>{model.backend}</dd>
                <dt>optimizer</dt>
                <dd>{model.optimizer_model}</dd>
                <dt>target</dt>
                <dd>{model.target_model}</dd>
                <dt>schedule</dt>
                <dd>
                  {train.num_epochs}ep · bs{train.batch_size} · lr
                  {train.learning_rate} · {train.lr_scheduler}
                </dd>
              </dl>
            </div>
          </section>
        </div>
      )}

      {/* Wizard nav */}
      <div className="row between mt">
        <button
          className="btn btn-ghost"
          type="button"
          disabled={idx === 0}
          onClick={() => setStep(STEPS[Math.max(0, idx - 1)])}
        >
          ← back
        </button>
        {step !== "launch" && (
          <button
            className="btn btn-primary"
            type="button"
            disabled={step === "skill" && !skill}
            onClick={() => setStep(STEPS[Math.min(STEPS.length - 1, idx + 1)])}
          >
            next →
          </button>
        )}
      </div>
    </div>
  );
}
