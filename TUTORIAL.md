# Tutorial — evolve a skill end-to-end

This walks the **full self-evolve loop** on a small, genuinely useful skill:

> **date-normalizer** — turn a human-written date ("5th March 2021", "Feb 14 '99")
> into ISO 8601 (`2021-03-05`, `1999-02-14`).

You start from a deliberately naive base skill, generate evals, run N optimization
cycles, watch each iteration accept or reject a mutation, compare versions and
scores, and end with a `best_skill.md` measured on a held-out test split.

Everything here is bundled in [`examples/date-normalizer/`](examples/date-normalizer/):
`skill.md` (base), `dataset.json` (24 cases), `grader.json` (exact match).

You can drive it from the **web UI** or from the **terminal (curl)** — both hit the
same backend. The curl path is fully reproducible, so it is the primary track; UI
notes are called out inline.

---

## 0. Install

```bash
./run.sh install          # venv + studio + SkillOpt engine + node deps (idempotent)
# add the LLM-judge grader too (optional, needs an API key later):
./run.sh install --with-geval
./run.sh doctor           # verify: python, venv, SkillOpt, deepeval, node, claude CLI, ports
```

`doctor` prints a ✓/–/✗ report. You need **SkillOpt engine installed** for real runs
(the `–` line tells you if it is missing). `exact` grading needs no judge model, so
date-normalizer runs with just a target-model API key.

Set the API key for your target/optimizer backend (OpenAI shown; the studio also
supports Azure and others via the Model panel / keyring):

```bash
export OPENAI_API_KEY=sk-...     # used by the target + optimizer models
```

Launch:

```bash
./run.sh run
# backend  → http://localhost:8000  (docs: /docs)
# frontend → http://localhost:5173
```

---

## 1. Point the studio at the base skill

The scanner finds skills in your **current working directory** (plus Claude/Codex/
OpenAI skill locations). The simplest path: launch from a directory that contains
the example, or pass the skill file directly to the run (Step 4, DIRECT shape).

**UI:** open <http://localhost:5173>, the left panel lists discovered skills — pick
`date-normalizer`. Its structure graph renders on the right.

**curl:** list what the scanner sees:

```bash
curl -s localhost:8000/api/skills | jq '.[].id'
```

---

## 2. Create the evals (dataset)

The dataset **is** the eval: each case is `{input, ground_truth}`, and the grader
scores the model's answer against `ground_truth`.

Two ways to get one:

**(a) Use the bundled dataset** — load `examples/date-normalizer/dataset.json`:

```bash
curl -s -X POST localhost:8000/api/datasets \
  -H 'content-type: application/json' \
  --data @examples/date-normalizer/dataset.json
# → {"name":"date-normalizer-eval","num_cases":24,"split_ratio":"5:2:3",...}
```

`split_ratio: "5:2:3"` = 5 parts train : 2 valid : 3 test (deterministic split).
Train drives the mutations, valid selects the best candidate, **test is held out**
and only scored at the end — that final number is the honest one.

**(b) Generate evals from natural language** (needs the local `claude` CLI):

```bash
curl -s -X POST localhost:8000/api/ai/generate-dataset \
  -H 'content-type: application/json' \
  -d '{"skill_id":"date-normalizer","instruction":"messy real-world dates: abbreviated months, ordinals, slashes, 2-digit years, ALL CAPS","count":24}'
```

This **drafts** cases into the editor — it never auto-applies. Review, edit, then
POST them as a dataset. **UI:** the Dataset editor has a "Generate with AI" button
and inline editing; you tweak rows before saving.

Ask the studio which grader fits your data:

```bash
curl -s "localhost:8000/api/graders/recommend?dataset=date-normalizer-eval"
# → {"type":"exact","rationale":"short single-token answers → exact match"}
```

---

## 3. Configure the grader

date-normalizer has canonical answers, so use **exact** (deterministic, free — no
judge model). That is `examples/date-normalizer/grader.json`:

```json
{ "type": "exact", "threshold": 1.0 }
```

`soft = 1.0` iff the trimmed output equals `ground_truth`; `hard = int(soft >= threshold)`.

Dry-run the grader on a couple of sample predictions before committing:

```bash
curl -s -X POST localhost:8000/api/graders/dry-run \
  -H 'content-type: application/json' \
  -d '{"type":"exact","threshold":1.0,"samples":[{"prediction":"2021-03-05","ground_truth":"2021-03-05"},{"prediction":"March 5 2021","ground_truth":"2021-03-05"}]}'
```

**Open-ended skills instead?** Set `"type":"geval"` with a `"criteria"` string (e.g.
"reward faithful, concise ISO output; penalize extra prose"), install `--with-geval`,
and set a **judge model** independent of the target/optimizer. You can hand-write the
criteria or draft them with `POST /api/ai/generate-geval`, then edit. G-Eval runs the
judge at temperature 0 with an optional self-consistency average and caches by
skill-version hash so unchanged outputs are not re-judged.

---

## 4. Launch the run — choose your cycles

**Cycles = `num_epochs`.** Each epoch sweeps the train split in minibatches; each
step proposes a mutated skill, evaluates it, and **ACCEPTs or REJECTs** by score.

DIRECT shape (points straight at the example files — no prior dataset POST needed):

```bash
RUN=$(curl -s -X POST localhost:8000/api/runs/train \
  -H 'content-type: application/json' \
  -d '{
    "slug": "date-normalizer-v1",
    "skill_path": "examples/date-normalizer/skill.md",
    "dataset_path": "examples/date-normalizer/dataset.json",
    "grader": { "type": "exact", "threshold": 1.0 },
    "model": {
      "backend": "openai_chat",
      "optimizer_model": "gpt-5.5",
      "target_model": "gpt-5.5"
    },
    "num_epochs": 3,
    "seed": 7,
    "launch": true
  }' | jq -r '.id')
echo "run id: $RUN"
```

- `num_epochs`: **how many cycles** (start with 2–3; raise to 5–8 to push further).
- `batch_size` / `seed`: reproducibility + minibatch size (optional).
- `optimizer_model` mutates the skill; `target_model` runs the skill under test.
  They can differ (a strong optimizer, a cheaper target).
- `"launch": false` returns the generated SkillOpt config **without running** — good
  for inspecting exactly what will execute.

**UI:** the Run panel has fields for epochs, seed, models, and grader; click **Launch**.

---

## 5. Watch each iteration live

Stream the run's events (Server-Sent Events):

```bash
curl -N localhost:8000/api/runs/$RUN/events
```

You will see the loop, step by step:

```
[EPOCH 1/3]
[STEP 1/8]
  1/6 rollout … 6/6 EVALUATE  ACCEPT  hard=0.62 soft=0.71   ← candidate kept
[STEP 2/8]
  … EVALUATE  REJECT  hard=0.55                              ← mutation discarded
```

- **ACCEPT** = the mutated skill beat the current best on the valid split → it becomes
  the new base for the next step.
- **REJECT** = mutation discarded, previous best retained.

**UI:** a live score chart + an accept/reject timeline update as events arrive.

---

## 6. Inspect changes, versions, and scores

Every accepted step writes a skill snapshot. Pull the version history and the score
series at any time (during or after the run):

```bash
# per-step skill snapshots (v0001, v0002, … + which one is best)
curl -s localhost:8000/api/runs/$RUN/versions | jq '.skill_versions[] | {step, is_best, path}'

# score trajectory (train + selection score per step) and the accept/reject gates
curl -s localhost:8000/api/runs/$RUN/scores   | jq '{score_series, gate_timeline}'
```

**Diff two versions** to see exactly what the optimizer changed between iterations:

```bash
V=examples/date-normalizer   # workspace-relative snapshots live under the run's outputs/
diff <(curl -s localhost:8000/api/runs/$RUN/versions | jq -r '.skill_versions[0].md_text') \
     <(curl -s localhost:8000/api/runs/$RUN/versions | jq -r '.skill_versions[-1].md_text')
```

Typically you will watch the skill grow from the naive base into explicit rules it
learned from failures — e.g. "accept abbreviated and ALL-CAPS months", "strip ordinal
suffixes (st/nd/rd/th)", "map 2-digit years: 00–69 → 20xx, 70–99 → 19xx", "zero-pad
month and day". **UI:** a version dropdown + side-by-side diff + a score-per-version
chart make this point-and-click.

---

## 7. Get the result

When the run finishes:

```bash
curl -s localhost:8000/api/runs/$RUN | jq '{status, final_test_score, best_skill_path}'
curl -s localhost:8000/api/runs/$RUN/versions | jq -r '.best_skill_text'   # the evolved skill
```

- `final_test_score` — accuracy on the **held-out test split** (never seen during
  optimization). This is the number that means something.
- `best_skill_text` / `best_skill.md` — your evolved skill, ready to copy back over
  `examples/date-normalizer/skill.md` (or wherever the real skill lives).

Re-evaluate any skill without re-optimizing (e.g. base vs evolved, apples-to-apples):

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/eval | jq '.final_test_score'
```

---

## 8. Iterate

- Base test score low? **Raise `num_epochs`** (more cycles) or enlarge the dataset
  (add the failure cases you saw in Step 5).
- Overfitting (train ≫ test)? Add variety to the dataset, or lower epochs.
- Answers open-ended (no single correct string)? Switch to a **geval** grader with
  criteria (Step 3) instead of exact.
- Happy with the evolved skill? Commit `best_skill.md` as the new base and start the
  next generation from there — the base skill genuinely self-evolves across runs.

That is the whole cycle: **base skill → evals → N cycles of mutate/score/accept →
inspect versions → held-out score → adopt the winner → repeat.**
