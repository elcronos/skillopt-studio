# SkillOpt Studio

A local, single-user web studio for optimizing **any** skill (Claude / Codex / OpenAI / cwd
skills) using Microsoft's MIT-licensed [SkillOpt](https://github.com/microsoft/SkillOpt).
Point it at a skill `.md`, attach a dataset and a grader, pick optimizer/target models, and
watch the skill evolve step-by-step. The optimized `best_skill.md` plus its held-out scores
are surfaced when the run completes.

> Status: scaffolded. Foundation + shared contracts are in place; feature packages
> (scanner, graph, dataset, grading, runner, frontend) are built incrementally and the
> backend imports their routers defensively so the server boots before they exist.

## Architecture

```
┌────────────────────┐     SSE / REST     ┌──────────────────────────────┐
│  React frontend     │ <───────────────> │  FastAPI backend              │
│  (Vite, :5173)      │                    │  skillopt_studio (:8000)      │
└────────────────────┘                    │   ├─ api/      REST + SSE     │
                                            │   ├─ scanner/  skill sources  │
         ┌─────────────────────────┐       │   ├─ graph/  ──┐              │
         │  Node graph-sidecar     │ <──────┤   ├─ dataset/  │ subprocess  │
         │  (SkillForge TS parser) │ stdin  │   ├─ grading/  │             │
         └─────────────────────────┘ stdout │   ├─ keys/     │             │
                                            │   ├─ events/    │            │
         ┌─────────────────────────┐       │   └─ skillopt/ ─┘             │
         │  SkillOpt (subprocess)  │ <──────┤    wraps scripts/train.py    │
         │  pinned-SHA editable    │ stdout │    + eval_only.py            │
         └─────────────────────────┘  argv  └──────────────────────────────┘
```

Components:
- **FastAPI backend** (`backend/skillopt_studio/`) — runs in the *same* venv as SkillOpt.
  Wraps SkillOpt's `scripts/train.py` / `eval_only.py` via subprocess (argv lists, never
  `shell=True`), streams stdout as SSE, and parses the `outputs/` run tree defensively.
- **React frontend** (`frontend/`) — Vite dev server on `:5173`.
- **Node graph-sidecar** (`graph-sidecar/`) — bundles SkillForge's deterministic TypeScript
  structure-graph parser; reads a skill `.md` on stdin and emits `{mermaid, nodes, edges,
  crossRefs}` on stdout. Per-request spawn for v1.
- **Wrapped SkillOpt** — installed by `run.sh` into the venv at a pinned commit; the studio
  never reimplements its optimization engine.

### The "any skill" approach (`generic_qa`)

Rather than code-generating a fragile per-skill Python environment, the studio ships one
reusable SkillOpt environment adapter, `generic_qa`, that implements SkillOpt's real
`EnvAdapter` interface. It does single-turn rollouts (system = the skill being optimized,
user = each dataset case's input) against the configured target backend, parses the answer,
and scores it with a configurable grader (`exact`, `fuzzy`, `f1`, `llm_judge`, or sandboxed
`custom_python`) producing `soft` (float 0..1) and `hard = int(soft >= threshold)`. Reflection
reuses SkillOpt's shared `run_minibatch_reflect`. This lets *any* skill be optimized through
one well-tested path. (Adapter implementation is a separate feature package.)

## Quickstart

```bash
./run.sh
```

`run.sh` will:
1. Discover a compatible Python (`python3.10`/`3.11`/`3.12`; **never** bare `python3` — the
   host default may be too new). It enforces `>=3.10,<3.14` and fails with a clear message.
2. Create or reuse `.venv/`.
3. `pip install -e .` (the studio) and install SkillOpt at its pinned SHA into the same venv
   (idempotent — skipped if `skillopt` already imports).
4. Build the Node graph-sidecar and frontend if present (`npm install`).
5. Launch the backend (uvicorn, `:8000`) and frontend (Vite, `:5173`) in parallel and print
   their URLs.

Then open the frontend at <http://localhost:5173> and the API at
<http://localhost:8000> (health: <http://localhost:8000/api/health>).

### Requirements
- Python 3.10–3.13 (3.10/3.11/3.12 verified). Host default `python3` is intentionally avoided.
- Node.js (for the graph-sidecar and frontend).
- API keys for your chosen backend(s) — stored via the OS keyring (macOS Keychain) with a
  `chmod 600 .keys.json` fallback. Keys are injected into subprocesses via environment
  variables only, never via argv or logs, and are scrubbed before custom scorers run.

## Layout

```
run.sh  pyproject.toml  README.md  NOTICE  .gitignore
backend/skillopt_studio/{main,config,domain}.py  api/  scanner/  graph/
                         skillopt/  dataset/  grading/  keys/  events/
graph-sidecar/{package.json, graph-cli.js, lib/*.ts}
frontend/src/{main,App}.tsx  lib/  components/  pages/
tests/{fixtures/{golden_run,sample_skills,sidecar_expected}, backend/, frontend/}
reference/  # verified-from-source SkillOpt copies (read-only contract material)
```

## Security model

Honest-mistake containment, not adversarial isolation (v1 is local, single-user, running
your own code): the custom-Python scorer runs in a child process with `resource` rlimits
(advisory on macOS), a 60s timeout, a temp working directory, an environment scrubbed of API
keys, and a score clamped to `[0, 1]`. A consent banner is shown before custom code runs. No
`shell=True` anywhere; SkillOpt subprocesses use `start_new_session=True` so cancellation can
signal the whole process group.

## Attribution / NOTICE

SkillOpt Studio wraps and depends on **Microsoft SkillOpt**, used under the MIT License.
The full notice is in [`NOTICE`](./NOTICE); the upstream license text is retained at
`reference/SkillOpt-LICENSE`.

> SkillOpt
> https://github.com/microsoft/SkillOpt
> Pinned commit: `8ebede0efdb69f6b74472fc8ad009f716bb4ca1b`
>
> MIT License
>
> Copyright (c) 2026 Microsoft Corporation
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Any redistributed skill artifacts (e.g. `best_skill.md`) produced via SkillOpt carry this
attribution.

The graph-sidecar bundles deterministic structure-graph parser source derived from
SkillForge; copied files carry a source-path + commit-SHA header comment.
