# SkillOpt train.py STDOUT contract

> Verified against the SkillOpt source at pinned SHA `8ebede0efdb69f6b74472fc8ad009f716bb4ca1b`:
> `skillopt/engine/trainer.py`, `skillopt/gradient/reflect.py`,
> `skillopt/envs/searchqa/rollout.py`, and the webui parser
> `skillopt_webui/app.py::_parse_stage` (mirrored in `reference/skillopt_webui_app.py`).
> `runner.py::parse_line` consumes these markers and emits `domain.SSEEvent`s.
> The subprocess runs with `PYTHONUNBUFFERED=1` so lines arrive live.

## Pipeline overview
Per epoch, per step, SkillOpt runs a 6-stage pipeline (the webui labels them
`Rollout, Reflect, Aggregate, Select, Update, Gate`). Stages print as `[N/6 ...]`.

## Verified markers

| Marker (substring / regex)                              | Source (trainer.py)                | Runner event |
|---------------------------------------------------------|------------------------------------|--------------|
| `[EPOCH x/y]`                                            | `print(f"\n  [EPOCH {epoch}/{num_epochs}] ...")` | `EpochEvent(epoch,total_epochs)` |
| `[STEP x/y]`                                             | `print(f"\n  [STEP {global_step}/{total_steps}] ...")` | `StepEvent(step,total_steps)` |
| `[1/6 ROLLOUT] train items=...`                         | stage 1 start                      | `StageEvent(index=1, stage="rollout")` |
| `[1/6 done] hard=.. soft=..`                            | stage 1 result                     | captures `last_train_score` |
| `[2/6 REFLECT minibatch] failure=..→.. success=..`      | `reflect.run_minibatch_reflect`    | `StageEvent(index=2, stage="reflect")` |
| `[2/6 done] failure_patches=.. ...`                     | stage 2 result                     | `StageEvent(index=2)` |
| `[3/6 done] merged N ...`                               | stage 3 (aggregate / merge)        | `StageEvent(index=3, stage="done")` |
| `[4/6 SELECT] M -> N ...`                               | stage 4                            | `StageEvent(index=4, stage="select")` |
| `[5/6 UPDATE] skill_len A -> B`                         | stage 5                            | `StageEvent(index=5, stage="update")` |
| `[6/6 EVALUATE] selection items=N`                      | stage 6 start                      | `StageEvent(index=6, stage="evaluate")` |
| `[6/6 EVALUATE] ACCEPT (new best) hard=.. > prev best ..` | gate accept-new-best             | `StepEvent(accepted=True, sel_score=..)` |
| `[6/6 EVALUATE] ACCEPT hard=.. > current=..`            | gate accept                        | `StepEvent(accepted=True, sel_score=..)` |
| `[6/6 EVALUATE] REJECT hard=.. <= current=..`           | gate reject                        | `StepEvent(accepted=False, sel_score=..)` |
| `[6/6 EVALUATE] cache hit <hash>: hard=..`              | gate selection-cache hit           | (scores captured if present) |
| `[rollout] N/total (acc=..) id=.. hard=0\|1`             | `searchqa.rollout.run_batch` / generic_qa | per-item `StageEvent("rollout_item:<id>:hard=N")` |
| `[rollout] N/total ... TIMEOUT`                         | rollout task timeout               | per-item progress |
| `[baseline result] selection hard=.. soft=.. gate[..]=..` | baseline eval                    | `StageEvent("baseline")` + `last_train_score` |
| `[SLOW UPDATE epoch N] ...` / `slow update`             | end-of-epoch slow update           | `StageEvent("slow update")` |
| `[meta skill] ...` / `meta skill`                       | end-of-epoch meta skill            | `StageEvent("meta skill")` |
| `Output saved to: <path>`                               | end of `main()`                    | captures `out_root` |
| `Final test: <float>`                                   | end of `main()` (if eval_test)     | `DoneEvent.final_test_score` |
| `Traceback (most recent call last):`                    | uncaught exception                 | `ErrorEvent(recoverable=False)` |
| line containing `error`/`fail` (non-rollout)            | various                            | `ErrorEvent` (recoverable if `warning`/`retry`) |

## Gate score metric
`evaluate_gate` uses `gate_metric` ∈ {`hard`,`soft`,`mixed`}. The `[6/6 EVALUATE]`
line's `score_label` is one of:
- `hard=<f>` (default), `soft=<f>`, or `mixed[w=<f>]=<f> (hard=<f> soft=<f>)`.
`runner.parse_line` extracts `mixed=` first, else `hard=`, else `soft=` as the
step's `sel_score`. `evaluation.use_gate` is **mandatory true** in this branch.

## On-disk reconciliation (authoritative scores)
stdout is the live signal; the run dir is authoritative for final scores. At each
`[STEP]` boundary, reconcile with:
- `outputs/<env>/<run>/history.json` — list of step records: `action`
  (`accept`/`accept_new_best`/`reject`), `selection_hard`/`selection_soft`,
  `candidate_gate_score`, `current_score`/`best_score`, `best_step`.
- `outputs/<env>/<run>/results.jsonl` (+ per-step `selection_eval/*.jsonl`) —
  rollout lines `{id,hard,soft,...}` and selection score lines.
- `outputs/<env>/<run>/skills/skill_v{step:04d}.md` and run-root `best_skill.md`.

## Assumptions / things to validate on a REAL run
- **`[2/6 done]` exact wording**: trainer prints `[2/6 done] failure_patches=..`;
  the webui matches `"2/6 reflect"` OR `("reflect" and "patch")`. `runner` keys on
  the `[N/6 ...]` regex which is robust to the trailing words.
- **`history.json` filename**: trainer calls `_save_history(out_root, history)`;
  the conventional filename is `history.json`. The parser also falls back to
  scanning `step_*/step_record.json` and any `*.jsonl`, so it tolerates a
  different history filename if a future version changes it.
- **Mixed-metric label**: regex `_RE_MIXED` assumes `mixed[...]=<f>`; confirm the
  exact bracket content on a real mixed-metric run.
