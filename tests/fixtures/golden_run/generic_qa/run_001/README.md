# SYNTHETIC golden run fixture — `generic_qa/run_001`

> **THIS IS A SYNTHETIC FIXTURE — NOT A REAL SKILLOPT RUN.**
> It is hand-authored to match the verified SkillOpt output schema
> (see `SKILLOPT_INTEGRATION.md`, pinned SHA `8ebede0…`). Swap it for a real
> `outputs/generic_qa/<run>/` tree once a live run is available.

## Why it exists
`backend/skillopt_studio/skillopt/probe.py::run_probe()` replays this tree through
`outputs.parse_run_tree()` on server startup and at `/api/health`, failing loud if
the parser and the on-disk schema ever diverge. It lets the output parser and the
results API be developed and regression-tested without API keys, cost, or a ~30min run.

## Layout (mirrors what `skillopt.engine.trainer` writes)
```
run_001/
├── config.yaml                  # resolved run config (model/train/optimizer/evaluation/env)
├── best_skill.md                # best skill (trainer writes this at run-root, NOT skills/)
├── history.json                 # list[step_record]: action (accept/accept_new_best/reject),
│                                 #   selection_hard/soft, candidate_gate_score, current/best score
├── results.jsonl                # JSONL: rollout lines {id,hard,soft,...} + selection score lines {score,step,phase}
├── skills/
│   ├── skill_v0000.md           # seed snapshot (step 0)
│   ├── skill_v0001.md           # per-step snapshot
│   └── skill_v0002.md
└── predictions/
    ├── q1/conversation.json     # target conversation + [EVALUATION RESULT] system turn
    ├── q2/conversation.json
    └── q3/conversation.json
```

## Schema notes / assumptions (flagged for a real-run swap)
- `best_skill.md` is at the **run root** per the verified trainer source
  (`with open(os.path.join(out_root, "best_skill.md"), "w")`). The integration doc
  mentioned `skills/best_skill.md`; the parser accepts **both** locations defensively.
- The verified trainer writes step records via `_save_history` — exact filename
  (`history.json`) is the conventional name; the parser also scans `step_*/step_record.json`
  and `**/*.jsonl` as fallbacks, so it is robust to the precise history filename.
- `results.jsonl` here co-locates rollout lines and selection score lines in one file;
  a real run may split these across `results.jsonl` and per-step `selection_eval/*.jsonl`.
  The parser greps **all** `*.jsonl` and classifies by fields (`hard`/`soft` → rollout,
  `score`+`phase=selection` → gate), so either layout parses.
