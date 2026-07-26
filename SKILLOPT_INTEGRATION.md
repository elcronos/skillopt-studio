# SkillOpt Integration Reference (VERIFIED from source)

> Authoritative contract for SkillOpt Studio. Every fact here was verified by reading
> the actual `microsoft/SkillOpt` source at pinned SHA **`8ebede0efdb69f6b74472fc8ad009f716bb4ca1b`**.
> When in doubt, the cloned source + `reference/` copies win over any doc or memory.
> ⚠️ The earlier project spec/plan contained schema details from an unreliable web fetch
> (e.g. `items.json`, `--optimizer_model` flags, `history.json`). Those were WRONG. Use THIS file.

## Package facts
- Name `skillopt`, version 0.1.0, MIT, `requires-python = ">=3.10"` (3.10/3.11/3.12 classifiers).
- Install (pinned): `pip install -e "git+https://github.com/microsoft/SkillOpt@8ebede0efdb69f6b74472fc8ad009f716bb4ca1b#egg=skillopt"`
  - Core deps: openai, pyyaml, numpy, openpyxl, azure-identity, azure-core, httpx.
  - Optional extras: `[claude]` (claude-agent-sdk), `[qwen]` (vllm), `[alfworld]`, `[webui]` (gradio), `[dev]` (ruff,pytest).
- Console scripts: `skillopt-train = scripts.train:main`, `skillopt-eval = scripts.eval_only:main`.
- Local host has python3.10.13 at `/opt/homebrew/bin/python3.10` (also 3.11, 3.12). Use one of these for the venv; NEVER bare `python3` (host default is 3.14.4, too new).

## CLI (REAL)
```
python scripts/train.py --config <config.yaml> [--cfg-options section.key=value ...]
python scripts/eval_only.py --config <config.yaml> --skill <skill.md> [--split test|valid|train]
python -m skillopt_webui.app [--port 7860] [--share]   # existing Gradio dashboard
```
- Overrides are `section.key=value` after `--cfg-options` (space-separated), NOT individual flags.
- Model is set in YAML: `model.optimizer`, `model.target`, `model.backend`, `model.optimizer_backend`, `model.target_backend`. API creds via env vars.
- Build argv as a list, never `shell=True`. Set `env["PYTHONUNBUFFERED"]="1"`. Use `start_new_session=True` so cancel can `os.killpg(os.getpgid(pid), SIGTERM)`.

## Config (REAL — structured YAML with `_base_` inheritance)
- Base: `configs/_base_/default.yaml`; per-env: `configs/<env>/default.yaml` with `_base_: ../_base_/default.yaml`.
- Sections: `model`, `train`, `gradient`, `optimizer`, `evaluation`, `env`. (See `reference/skillopt_base_config.yaml` for the full key set.)
- `skillopt.config.load_config(path, overrides)` + `flatten_config()` map structured→flat (`reference/` has the flatten map). Key ones:
  - `optimizer.learning_rate` → edit_budget (max edits/step), `optimizer.lr_scheduler` (cosine|linear|constant|autonomous).
  - `train.num_epochs`, `train.batch_size`, `train.seed`, `gradient.analyst_workers`, `gradient.minibatch_size`.
  - `evaluation.use_gate` (validation gating; **mandatory true** in this branch — flatten raises if false), `evaluation.eval_test`.
  - `env.name` (registry key), `env.skill_init` (path to seed skill .md — THIS is what gets optimized),
    `env.split_mode` (`ratio`|`split_dir`), `env.split_dir`, `env.data_path`, `env.split_seed`, `env.out_root`, `env.exec_timeout`.

## Outputs (REAL — no single history.json)
- Output tree: `outputs/<env_name>/<run_dir>/` (run dir like `run_001`/timestamped).
- Contains: `config.yaml` (resolved run config), `skills/best_skill.md` (+ per-version skill snapshots), `predictions/<task_id>/conversation.json`, and `**/*.jsonl` result logs (rollout/gate records, each line a JSON object; score lines carry a `score` field; rollouts carry `hard` (int 0/1) and `soft` (float 0..1)).
- The existing Gradio "Results" tab scans `outputs/<bench>/<run>/`, reads `config.yaml` for `train.num_steps`, and greps `**/*.jsonl` for `score`. Mirror this; do NOT assume a `history.json`.
- The Studio output parser must be DEFENSIVE: discover run dirs, read config.yaml, parse all *.jsonl, build the per-step score series + accepted/rejected (gate) timeline from the jsonl + stdout, locate best_skill.md and per-step skill versions.

## STDOUT contract (REAL — this is the SSE event source)
Verified from `skillopt_webui/app.py::_parse_stage`. Train subprocess stdout (unbuffered) emits:
- `[EPOCH x/y]` — epoch boundary (parse `x`,`y`).
- `[STEP x/y]` — step boundary (parse `x`,`y`).
- Stage markers per step: `1/6 rollout`, `2/6 reflect`, `3/6 aggregate`/`merge`, `4/6 select`, `5/6 update`, `6/6`/`gate ... score`.
- Epoch-boundary: `slow update`, `meta skill`. Also `baseline ... evaluate`.
- Per-item rollout lines: `[ROLLOUT] ... hard=1|hard=0 ... [timeout]`.
- `error`/`fail` lines.
Studio's runner parses these line-by-line → SSE events (stdout authoritative); reconcile scores with the run dir's *.jsonl at each step boundary. Document any newly observed lines in backend `skillopt/STDOUT_CONTRACT.md`.

## Env adapter interface (REAL — `reference/skillopt_env_base.py`)
`skillopt.envs.base.EnvAdapter` (ABC). Real concrete shape (see `reference/skillopt_searchqa_adapter.py`, 129 LOC):
- `__init__(self, cfg)`, `setup(cfg)`, `get_dataloader() -> BaseDataLoader|None`.
- `build_train_env(self, batch_size, spec: BatchSpec, **kw)`, `build_eval_env(self, env_num, split, seed, **kw)`.
- `rollout(self, env, skill_content, out_dir, **kw) -> list[dict]` where each dict has at least `{"id", "hard": int(0/1), "soft": float}` (+ optional question/predicted_answer/fail_reason/reference_text...). searchqa delegates to `searchqa.rollout.run_batch`.
- `reflect(self, results, skill_content, out_dir, **kw)` — searchqa delegates to `skillopt.gradient.reflect.run_minibatch_reflect(...)`. REUSE this shared reflect; do not reinvent.
- `get_task_types()`.
- Dataloader (`skillopt.datasets.base.BaseDataLoader`): items are dicts/DataItem with `id`, `input`, `ground_truth`, `metadata`; splits `train`/`valid`/`test`; `split_mode` `ratio` (deterministic from data_path) or `split_dir`.
- ⚠️ The simplified `execute()/evaluate()/TaskResult` shown in `docs/guide/new-benchmark.md` and `_template/env_template.py` is AspIRATIONAL/simplified. The REAL trainer calls `build_train_env`/`rollout`/`reflect`. Model the generator on the searchqa adapter + base.py, NOT the doc.
- Registration: `scripts/train.py::_register_builtins()` lazily imports adapters into `_ENV_REGISTRY` keyed by `env.name` (try/except ImportError per env). `skillopt/envs/__init__.py` is essentially empty — registration happens in train.py. To add a custom env, the installed `skillopt/envs/<name>/` must exist AND `_register_builtins` must import it. Studio strategy below.

## STUDIO STRATEGY: optimize ANY skill (the core feature)
Decision (user: "best solution, optimise any kind of skill, not only examples"):
Ship ONE reusable generic adapter rather than code-generating fragile per-skill Python.
- Studio bundles `skillopt_studio_envs/generic_qa/{__init__.py, env.py, loader.py}` implementing the REAL interface:
  - `loader.py`: reads a standard dataset file `dataset.json` = list of `{"id","input","ground_truth","metadata"}`; supports `split_mode: ratio` (split_ratio like "2:1:7") and `split_dir`.
  - `env.py::GenericQAEnv`: single-turn rollout — system=skill_content, user=item.input via the configured target model backend; parse via configurable regex/`Answer:`/json; score via a SCORING SPEC: `exact` | `fuzzy` | `f1` | `llm_judge` (rubric) | `geval` (DeepEval G-Eval) | `custom_python` (sandboxed) → `soft` float, `hard = int(soft >= threshold)`. reflect → `run_minibatch_reflect`.
  - **G-Eval grader (`geval`)**: implement via DeepEval (`deepeval` optional dep, extra `[geval]`) `GEval` metric — user supplies criteria/evaluation_steps; score is the normalized 0..1 → `soft`. HARDENING (mandatory, because SkillOpt warns noisy metrics confuse the optimizer): pin judge model + temperature 0; optional self-consistency (avg of N); **cache results by (skill_version_hash, case_id, judge_model)** so unchanged outputs aren't re-judged; judge model independent of target/optimizer; record judge model+criteria in run metadata. Best for open-ended/free-text skills; NOT for verifiable answers (use exact/f1 there). DeepEval is optional — if not installed, `geval` is disabled with a clear message; exact/fuzzy/f1 always available.
  - **Metric recommender** ("analyse workflow & suggest"): a helper that inspects the dataset's `ground_truth` distribution and recommends a grader — short factual/single-token → exact or f1; long free-text / multi-sentence / no canonical answer → geval (or llm_judge); JSON/structured → schema/exact. Surfaced as a non-binding suggestion in GraderConfig UI with a one-line rationale. Also estimate judge-call volume + rough cost for geval/llm_judge before a run.
- Registration: install-time hook adds `generic_qa` to SkillOpt's registry. Cleanest robust approach: studio writes `generic_qa` into the cloned editable `skillopt/envs/generic_qa/` AND appends a try/except import block to `_register_builtins` in the cloned `scripts/train.py` (idempotent patch, recorded). Fallback: a `sitecustomize`/wrapper that injects into `_ENV_REGISTRY` before train. The backend executor MUST read the full `scripts/train.py` registration block and pick the working mechanism, then add a test that `--config configs/generic_qa/<slug>.yaml` resolves the env.
- Per-skill run = generate `configs/generic_qa/<slug>.yaml` (`_base_` the SkillOpt base) with `env.name: generic_qa`, `env.skill_init: <user skill.md>`, `env.data_path: <user dataset.json>`, scoring section, model/train/optimizer params from the UI; launch train.py; stream; parse `outputs/generic_qa/<run>/`.
- Custom-python scorer sandbox = honest-mistake containment: child process, `resource` rlimits (advisory on macOS), 60s timeout, temp cwd, env scrubbed of API keys, score clamped to [0,1]. Consent banner. NOT adversarial isolation.

## Dataset (REAL examples)
- searchqa uses `env.split_mode: split_dir`, `env.split_dir: data/searchqa_split` with per-split JSON of `{"id": ...}` (content resolved by the env). For Studio generic_qa, the dataset is self-contained `{id,input,ground_truth,metadata}` (no external corpus needed).

## Keys / backends (REAL — `.env.example`)
- Backends: `openai_chat` (Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_API_KEY`, or `AZURE_OPENAI_AUTH_MODE=azure_cli|managed_identity`), `openai_compatible` (`AZURE_OPENAI_AUTH_MODE=openai_compatible`, reuse endpoint/key for api.openai.com/v1), `claude_chat` (`ANTHROPIC_API_KEY`), `qwen_chat` (`QWEN_CHAT_BASE_URL`/`QWEN_CHAT_MODEL`), `minimax_chat` (`MINIMAX_BASE_URL`/`MINIMAX_API_KEY`/`MINIMAX_MODEL`).
- Per-role overrides via `OPTIMIZER_AZURE_OPENAI_*` / `TARGET_AZURE_OPENAI_*` env; base inherits if unset (webui does this propagation).
- Studio stores keys via OS keyring (macOS Keychain) + chmod-600 `.keys.json` fallback (gitignored); injects to the train subprocess via `env`, NEVER argv/logs; scrubs before custom scorers.

## Golden fixture (Phase 0 decision: SYNTHESIZE from this schema)
- No outputs/ bundled in the repo; a real run needs API keys + ~30min + cost. Per user, SYNTHESIZE a representative `tests/fixtures/golden_run/generic_qa/run_001/` matching the schema above (config.yaml + skills/best_skill.md + per-version skills + *.jsonl with rollout hard/soft + gate score lines + predictions/). Mark it `SYNTHETIC` in a README so it's swapped for a real run later. The fixture-replay schema probe at `/api/health` parses it on startup and fails loud on parser/schema divergence.

## License obligation
- SkillOpt MIT. `reference/SkillOpt-LICENSE` retained. README + NOTICE must carry the SkillOpt copyright; any redistributed best_skill.md/outputs carry attribution.
