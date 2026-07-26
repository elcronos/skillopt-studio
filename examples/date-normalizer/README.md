# Example: date-normalizer

A small, genuinely useful skill for the full self-evolve walkthrough in
[`../../TUTORIAL.md`](../../TUTORIAL.md).

**Task:** turn a human-written date into ISO 8601.
`"5th March 2021" → 2021-03-05`, `"Feb 14 '99" → 1999-02-14`.

| File | Role |
|------|------|
| `skill.md`     | The **base** skill — deliberately naive (handles only a couple of formats). |
| `dataset.json` | 24 eval cases (`input` → `ground_truth`), split `5:2:3` train:valid:test. |
| `grader.json`  | `exact` match — deterministic, no judge model, so the first run is free. |

Why this example: correctness is objectively checkable (exact string match), so you
see real score movement without paying for an LLM judge, and the naive base skill has
obvious room to evolve (abbreviated/ALL-CAPS months, ordinal suffixes, slashes,
2-digit years). Swap in your own `skill.md` + `dataset.json` to optimize anything.

Quick start (backend running via `./run.sh`):

```bash
curl -s -X POST localhost:8000/api/runs/train -H 'content-type: application/json' -d '{
  "slug":"date-normalizer-v1",
  "skill_path":"examples/date-normalizer/skill.md",
  "dataset_path":"examples/date-normalizer/dataset.json",
  "grader":{"type":"exact","threshold":1.0},
  "model":{"backend":"openai_chat","optimizer_model":"gpt-5.5","target_model":"gpt-5.5"},
  "num_epochs":3,"seed":7,"launch":true
}'
```

Full step-by-step (generate evals, watch iterations, diff versions, read scores) is in
[`TUTORIAL.md`](../../TUTORIAL.md).
