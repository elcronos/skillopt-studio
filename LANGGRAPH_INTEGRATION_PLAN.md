# SkillOpt Studio × skill-to-langgraph — Integration Plan

Add a **"Convert to LangGraph"** feature to SkillOpt Studio: pick any scanned
skill, click convert, watch progress stream live, and get a runnable
`dist/<skill>/` LangGraph project + parity scores surfaced in the UI.

Mirrors the existing SkillOpt-wrapping pattern exactly (subprocess + SSE +
defensive output parsing). No new architecture invented.

---

## 1. What each side provides

**skill-to-langgraph** (`~/Desktop/skill-to-langgraph`)
- Pipeline: SKILL.md → graphspec.json → codegen → validate → gen_evals → pytest
  → package_standalone → (optional) parity_run → self_improve.
- Steps 2–9 are **deterministic scripts** under `scripts/`, run with its own
  `.venv/bin/python`. LLM backend = `claude -p` (no API key).
- **Step 1 (SKILL.md → graphspec.json) is the only LLM-judgment step and has NO
  script** — today a human Claude writes it in-conversation. This is the gap the
  integration must close to run headless.
- Deliverable: `dist/<skill>/` (graph + runtime + main.py + requirements).

**SkillOpt Studio** (`~/Desktop/02_AI_Dev/skillopt-studio`)
- FastAPI backend, routers mounted defensively in `main.py` (`_ROUTER_MODULES`).
- `scanner/` discovers skills (claude/codex/openai/cwd) → `Skill{id, body, source_path}`.
- `skillopt/runner.py` = subprocess → stdout-line → `events.bus.publish(run_id, event)`
  → SSE; `RunHandle.cancel()` SIGTERMs the process group. In-memory run registry in `api/runs.py`.
- `ai/claude_cli.py` = `claude -p <prompt> --output-format json` + robust JSON
  extraction (tolerates ```json fences/prose). **Reuse this for step 1.**
- `graph/` already shells a Node sidecar per skill (precedent for "run a tool on a skill body").

---

## 2. The one real problem: headless graphspec (step 1)

The web app can't have Claude in the loop, so we add a headless graphspec
generator. Two layers:

- **In skill-to-langgraph**: new `scripts/extract_graphspec.py`
  - Input: a target skill dir (or SKILL.md path).
  - Loads `schemas/graphspec.schema.json` + `training/patterns.json` +
    `training/learnings.md` (the step-0 memory) and the modeling rules from
    SKILL.md §1.
  - Builds one prompt → calls `claude -p ... --output-format json` (its own
    `claude_cli_llm.py`, already present) → extracts JSON → validates against the
    schema with `jsonschema` → writes `training/specs/<skill>.graphspec.json`.
  - Handles subgraph dependency order (SKILL.md rule: "convert leaves before
    parents"): detect `subgraph` nodes, recurse on children first.
  - Exit 0 + path on success; non-zero + stderr on schema-validation failure.
  - **Why here, not in the studio:** keeps the skill self-contained and usable
    standalone (CLI users get headless conversion too), and the schema/memory
    live next to it.

- **In the studio**: an adapter that invokes this script as the first pipeline
  stage. If `extract_graphspec.py` is absent (older skill checkout), the studio
  falls back to `ai/claude_cli.py` to draft the graphspec itself — same prompt,
  studio-side — so the feature degrades gracefully.

---

## 3. Backend changes (SkillOpt Studio)

New package `backend/skillopt_studio/langgraph/` (subprocess orchestration,
parallels `skillopt/`):

- `config.py` additions:
  - `LANGGRAPH_SKILL_DIR: Path` — resolve `~/Desktop/skill-to-langgraph`,
    overridable via env `SKILLOPT_LANGGRAPH_DIR`. Existence checked at call time
    (not import) so the router still mounts if absent.
  - `LANGGRAPH_VENV_PYTHON = LANGGRAPH_SKILL_DIR / ".venv" / "bin" / "python"`.

- `langgraph/pipeline.py` — defines the ordered stages, each an argv list run
  against the skill-to-langgraph `.venv`:
  1. `extract_graphspec.py <skill-dir>` (or studio-side claude_cli fallback)
  2. `validate_graph.py specs/<skill>.graphspec.json --report reports/<skill>.json`
  3. `gen_evals.py specs/<skill>.graphspec.json`
  4. `-m pytest evals/test_<skill>.py -q`
  5. `package_standalone.py specs/<skill>.graphspec.json`  → `dist/<skill>/`
  6. (optional, gated) `parity_run.py ...` with `RUN_LIVE_EVALS=1`
  7. `self_improve.py`
  - Each stage streams stdout via the **same** line-to-bus mechanism as
    `skillopt/runner.py`. Factor the shared streaming loop into a small
    `_stream_subprocess(argv, cwd, env, on_event)` helper (either reuse
    `runner`'s internals or lift them). `start_new_session=True`, no `shell=True`,
    SIGTERM-able process group — identical security posture to existing runs.

- `langgraph/outputs.py` — defensive parser for the deliverable:
  reads `reports/<skill>.json` (6 validation checks), pytest summary,
  `dist/<skill>/` file listing + README, and `reports/<skill>.parity.json` if
  present. Degrades to partial on missing files (like `skillopt/recovery.py`).

- `api/conversions.py` — new router `prefix="/api/conversions"`, added to
  `_ROUTER_MODULES` in `main.py` (one-line addition):
  - `POST /api/conversions`            `{skill_id, run_parity?: bool}` → resolve
    skill via scanner (reuse `runs._resolve_skill_path` logic / scanner registry),
    confine the target path, launch pipeline in a background thread, return
    `{conversion_id, status}`. In-memory registry mirroring `_RUNS`.
  - `GET  /api/conversions`            → list.
  - `GET  /api/conversions/{id}`       → status + parsed outputs (dist path,
    checks, pytest, parity).
  - `POST /api/conversions/{id}/cancel`→ SIGTERM the process group.
  - SSE: reuse the existing `events.bus` + `api/stream.py` topic
    (`conversion_id` as the bus key) — frontend subscribes the same way as runs.

Path confinement: the resolved skill dir must stay within an allowed root
(scanner source roots); reuse the `_confined()` guard pattern from `runs.py`.

---

## 4. Frontend changes

- `lib/api.ts`: `createConversion`, `getConversion`, `listConversions`,
  `cancelConversion`, and the SSE subscribe (reuse the runs stream hook).
- New `pages/ConvertPage.tsx` (or a tab on the existing skill detail view):
  - Skill picker (reuse the scanner-backed skill list already used by training).
  - "Run live parity" toggle (off by default — it costs LLM calls).
  - "Convert to LangGraph" button → POST, then live log panel fed by SSE
    (reuse the run log component).
  - Result card: 6 validation checks ✓/✗, pytest pass/fail, the `dist/<skill>/`
    path + file tree, copy-paste run command
    (`cd dist/<skill> && pip install -r requirements.txt && python main.py`),
    and parity scores if run.
- Add a nav entry. Keep styling consistent with existing pages.

---

## 5. Test plan

- **Backend unit** (`tests/backend/`): mock the subprocess layer; assert stage
  ordering, argv construction (correct venv python, cwd = skill-to-langgraph
  dir), env carries no secrets into argv, cancel SIGTERMs the group, and
  `outputs.py` degrades to partial on missing files.
- **extract_graphspec.py** (in skill-to-langgraph): golden test against the
  shipped `hello-world` worked example — generated graphspec must validate and
  match the committed `training/specs/hello-world.graphspec.json` shape
  (channels/nodes/edges), using a stubbed `claude_cli_llm` so it's offline.
- **End-to-end smoke** (manual / gated): convert `hello-world` through the studio
  → expect `dist/hello-world/` with all 5 package guardrails green and pytest
  passing. (hello-world also exercises subgraph composition via `random_number`.)
- **Frontend**: component test for the result card render from a fixture payload.

---

## 6. Build order (incremental, each independently shippable)

1. `scripts/extract_graphspec.py` in skill-to-langgraph + its golden test.
   (Unblocks everything; usable standalone immediately.)
2. `langgraph/` backend package (pipeline + outputs) with the shared streaming
   helper; unit tests with mocked subprocess.
3. `api/conversions.py` + one-line `main.py` mount + reuse stream/bus.
4. Frontend page + api client + nav.
5. E2E smoke on hello-world; wire parity toggle.
6. Docs: README "Convert to LangGraph" section + NOTICE note (the produced
   `dist/` carries skill-to-langgraph provenance, same as best_skill.md carries
   SkillOpt's).

---

## 7. Open decisions (defaults chosen, change if desired)

- **skill-to-langgraph location**: default `~/Desktop/skill-to-langgraph`, env
  override `SKILLOPT_LANGGRAPH_DIR`. (Could instead vendor it as a sibling or git
  submodule for portability — heavier.)
- **Parity off by default** (costs LLM calls) — opt-in toggle.
- **graphspec home**: written into skill-to-langgraph's `training/specs/`
  (its self-improvement memory benefits). Alternative: write into the studio's
  `outputs/` to keep the skill dir read-only — loses the step-6 learning loop.
- **No edit of `skillopt/` internals** beyond optionally lifting the streaming
  helper; conversions stay a separate package so SkillOpt runs are untouched.
