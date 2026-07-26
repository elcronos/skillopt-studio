#!/usr/bin/env bash
# SkillOpt Studio launcher.
#
# Discovers a compatible Python (>=3.10,<3.14), creates/reuses a venv, installs the
# studio + pinned SkillOpt into it, builds the Node graph-sidecar and frontend if
# present, then launches the backend (uvicorn) and frontend (vite) in parallel.
#
# Robust to components not yet existing: guards/echo-skips so it works while other
# packages are built in parallel. NEVER uses bare `python3` (host default may be too
# new). No secrets are echoed. Subprocesses are launched with argv, not shell strings.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
SKILLOPT_SHA="8ebede0efdb69f6b74472fc8ad009f716bb4ca1b"
SKILLOPT_SPEC="git+https://github.com/microsoft/SkillOpt@${SKILLOPT_SHA}#egg=skillopt"
BACKEND_PORT="8000"
FRONTEND_PORT="5173"

log()  { printf '[run.sh] %s\n' "$*"; }
fail() { printf '[run.sh] ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. Discover a compatible Python -----------------------------------------
PYTHON_BIN=""
for cand in python3.10 python3.11 python3.12 python3.13; do
  if command -v "$cand" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$cand")"
    break
  fi
done

[ -n "$PYTHON_BIN" ] || fail "No suitable Python found. Need python3.10/3.11/3.12 on PATH (NOT bare python3). Install one (e.g. 'brew install python@3.12')."

# Verify >=3.10,<3.14 via the interpreter itself (exit 0 == ok).
if ! "$PYTHON_BIN" -c 'import sys; v=sys.version_info; sys.exit(0 if (3,10) <= (v.major,v.minor) < (3,14) else 1)'; then
  PYV="$("$PYTHON_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
  fail "Python $PYV at $PYTHON_BIN is out of range. Need >=3.10,<3.14. Host default python3 is intentionally avoided."
fi
log "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'))"

# --- 2. Create / reuse venv --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  log "Creating venv at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  log "Reusing existing venv at $VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || fail "venv python missing at $VENV_PY"

# --- 3. Install studio + pinned SkillOpt (idempotent) ------------------------
log "Upgrading pip"
"$VENV_PY" -m pip install --quiet --upgrade pip

log "Installing studio (pip install -e .)"
"$VENV_PY" -m pip install --quiet -e .

if "$VENV_PY" -c 'import skillopt' >/dev/null 2>&1; then
  log "SkillOpt already importable in venv; skipping install (pin $SKILLOPT_SHA)"
else
  log "Installing SkillOpt at pinned SHA $SKILLOPT_SHA"
  "$VENV_PY" -m pip install -e "$SKILLOPT_SPEC"
fi

# --- 4. Build Node graph-sidecar (guarded) -----------------------------------
if [ -f "$REPO_ROOT/graph-sidecar/package.json" ]; then
  if [ ! -d "$REPO_ROOT/graph-sidecar/node_modules" ]; then
    if command -v npm >/dev/null 2>&1; then
      log "Installing graph-sidecar deps"
      ( cd "$REPO_ROOT/graph-sidecar" && npm install )
    else
      log "SKIP graph-sidecar: npm not found on PATH"
    fi
  else
    log "graph-sidecar deps already installed"
  fi
else
  log "SKIP graph-sidecar: not built yet (no graph-sidecar/package.json)"
fi

# --- 5. Install frontend deps (guarded) --------------------------------------
FRONTEND_READY="no"
if [ -f "$REPO_ROOT/frontend/package.json" ]; then
  if command -v npm >/dev/null 2>&1; then
    if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
      log "Installing frontend deps"
      ( cd "$REPO_ROOT/frontend" && npm install )
    else
      log "frontend deps already installed"
    fi
    FRONTEND_READY="yes"
  else
    log "SKIP frontend: npm not found on PATH"
  fi
else
  log "SKIP frontend: not built yet (no frontend/package.json)"
fi

# --- 6. Launch backend + frontend in parallel --------------------------------
PIDS=()
cleanup() {
  log "Shutting down..."
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid:-}" ] && kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

log "Starting backend: http://localhost:${BACKEND_PORT} (health: /api/health, docs: /docs)"
PYTHONPATH="$REPO_ROOT/backend" "$VENV_PY" -m uvicorn skillopt_studio.main:app \
  --host 127.0.0.1 --port "$BACKEND_PORT" --reload &
PIDS+=("$!")

if [ "$FRONTEND_READY" = "yes" ]; then
  log "Starting frontend: http://localhost:${FRONTEND_PORT}"
  ( cd "$REPO_ROOT/frontend" && npm run dev -- --port "$FRONTEND_PORT" ) &
  PIDS+=("$!")
else
  log "Frontend not started (not built yet). Backend only."
fi

log "Up. Press Ctrl-C to stop."
wait
