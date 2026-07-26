#!/usr/bin/env bash
# SkillOpt Studio launcher + installer + doctor.
#
# Usage:
#   ./run.sh                 install (idempotent) then launch backend + frontend
#   ./run.sh install         install deps only, do not launch
#   ./run.sh doctor          preflight: check every dependency and print a report
#   ./run.sh run             launch only (assumes install already ran)
#   ./run.sh --help
#
# Flags (for install / default):
#   --with-geval             also install the DeepEval G-Eval extra (LLM-judge grader)
#   --with-skillopt          install Microsoft SkillOpt at the pinned SHA (default: on)
#   --no-skillopt            skip SkillOpt install (UI-only exploration; runs cannot launch)
#   --backend-port=N         backend port (default 8000)
#   --frontend-port=N        frontend port (default 5173)
#
# NEVER uses bare `python3` (host default may be too new). No secrets are echoed.
# Subprocesses are launched with argv, not shell strings.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
SKILLOPT_SHA="8ebede0efdb69f6b74472fc8ad009f716bb4ca1b"
SKILLOPT_SPEC="git+https://github.com/microsoft/SkillOpt@${SKILLOPT_SHA}#egg=skillopt"
BACKEND_PORT="8000"
FRONTEND_PORT="5173"

WITH_GEVAL="no"
WITH_SKILLOPT="yes"
CMD="default"

log()  { printf '[run.sh] %s\n'          "$*"; }
warn() { printf '[run.sh] WARN: %s\n'    "$*" >&2; }
fail() { printf '[run.sh] ERROR: %s\n'   "$*" >&2; exit 1; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
dash() { printf '  \033[33m–\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

# --- arg parse ---------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    install|doctor|run) CMD="$arg" ;;
    --with-geval)       WITH_GEVAL="yes" ;;
    --with-skillopt)    WITH_SKILLOPT="yes" ;;
    --no-skillopt)      WITH_SKILLOPT="no" ;;
    --backend-port=*)   BACKEND_PORT="${arg#*=}" ;;
    --frontend-port=*)  FRONTEND_PORT="${arg#*=}" ;;
    -h|--help)          sed -n '2,19p' "$0"; exit 0 ;;
    *) fail "unknown argument: $arg (try --help)" ;;
  esac
done

# --- python discovery (shared) ----------------------------------------------
discover_python() {
  local cand
  for cand in python3.10 python3.11 python3.12 python3.13; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "$cand")"
      if "$PYTHON_BIN" -c 'import sys; v=sys.version_info; sys.exit(0 if (3,10)<=(v.major,v.minor)<(3,14) else 1)'; then
        return 0
      fi
    fi
  done
  PYTHON_BIN=""
  return 1
}

# ===========================================================================
# doctor — read-only preflight
# ===========================================================================
doctor() {
  log "SkillOpt Studio doctor"
  local problems=0

  if discover_python; then
    ok "python: $PYTHON_BIN ($("$PYTHON_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'))"
  else
    bad "python: need python3.10/3.11/3.12/3.13 on PATH (bare python3 is ignored)"; problems=$((problems+1))
  fi

  if [ -x "$VENV_DIR/bin/python" ]; then
    ok "venv: $VENV_DIR"
    local vpy="$VENV_DIR/bin/python"
    "$vpy" -c 'import skillopt_studio' 2>/dev/null && ok "studio package importable" || dash "studio not installed yet (run: ./run.sh install)"
    "$vpy" -c 'import skillopt'         2>/dev/null && ok "SkillOpt engine installed (mutation available)" || dash "SkillOpt not installed — runs cannot launch (./run.sh install --with-skillopt)"
    "$vpy" -c 'import deepeval'         2>/dev/null && ok "deepeval installed (G-Eval grader enabled)"     || dash "deepeval not installed — geval grader disabled (./run.sh install --with-geval)"
  else
    dash "venv: not created yet (run: ./run.sh install)"
  fi

  command -v node   >/dev/null 2>&1 && ok "node: $(node --version)"  || dash "node not found — frontend + graph-sidecar disabled"
  command -v npm    >/dev/null 2>&1 && ok "npm:  $(npm --version)"   || dash "npm not found — frontend + graph-sidecar disabled"
  command -v claude >/dev/null 2>&1 && ok "claude CLI available (AI dataset/criteria drafting enabled)" || dash "claude CLI not found — AI draft endpoints return 503 (optional)"

  for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if command -v lsof >/dev/null 2>&1 && lsof -i ":$p" >/dev/null 2>&1; then warn "port $p is in use"; else ok "port $p free"; fi
  done

  if [ "$problems" -gt 0 ]; then warn "$problems blocking problem(s) found."; return 1; fi
  log "doctor: no blocking problems."
}

# ===========================================================================
# install — create venv + deps (idempotent)
# ===========================================================================
install() {
  discover_python || fail "No suitable Python found. Need python3.10/3.11/3.12/3.13 on PATH (NOT bare python3). e.g. 'brew install python@3.12'."
  log "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'))"

  if [ ! -d "$VENV_DIR" ]; then log "Creating venv at $VENV_DIR"; "$PYTHON_BIN" -m venv "$VENV_DIR"; else log "Reusing venv at $VENV_DIR"; fi
  local VENV_PY="$VENV_DIR/bin/python"
  [ -x "$VENV_PY" ] || fail "venv python missing at $VENV_PY"

  log "Upgrading pip"
  "$VENV_PY" -m pip install --quiet --upgrade pip

  if [ "$WITH_GEVAL" = "yes" ]; then
    log "Installing studio + [geval] extra (DeepEval)"
    "$VENV_PY" -m pip install --quiet -e ".[dev,geval]"
  else
    log "Installing studio (pip install -e .[dev])"
    "$VENV_PY" -m pip install --quiet -e ".[dev]"
  fi

  if [ "$WITH_SKILLOPT" = "yes" ]; then
    if "$VENV_PY" -c 'import skillopt' >/dev/null 2>&1; then
      log "SkillOpt already importable; skipping (pin $SKILLOPT_SHA)"
    else
      log "Installing SkillOpt at pinned SHA $SKILLOPT_SHA (clones from GitHub)…"
      if ! "$VENV_PY" -m pip install "$SKILLOPT_SPEC"; then
        warn "SkillOpt install failed (network/git?). The studio UI still runs, but"
        warn "optimization runs cannot launch until SkillOpt installs. Retry:"
        warn "  ./run.sh install --with-skillopt"
      fi
    fi
  else
    log "Skipping SkillOpt install (--no-skillopt). Runs cannot launch; UI-only."
  fi

  if command -v npm >/dev/null 2>&1; then
    if [ -f "$REPO_ROOT/graph-sidecar/package.json" ] && [ ! -d "$REPO_ROOT/graph-sidecar/node_modules" ]; then
      log "Installing graph-sidecar deps"; ( cd "$REPO_ROOT/graph-sidecar" && npm install --silent )
    fi
    if [ -f "$REPO_ROOT/frontend/package.json" ] && [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
      log "Installing frontend deps"; ( cd "$REPO_ROOT/frontend" && npm install --silent )
    fi
  else
    warn "npm not found — frontend + graph-sidecar skipped (backend still works)."
  fi

  log "Install complete. Next: ./run.sh doctor  or  ./run.sh run"
}

# ===========================================================================
# run — launch backend + frontend
# ===========================================================================
launch() {
  local VENV_PY="$VENV_DIR/bin/python"
  [ -x "$VENV_PY" ] || fail "venv missing — run './run.sh install' first."

  local FRONTEND_READY="no"
  [ -d "$REPO_ROOT/frontend/node_modules" ] && FRONTEND_READY="yes"

  local PIDS=()
  cleanup() { log "Shutting down…"; for pid in "${PIDS[@]:-}"; do [ -n "${pid:-}" ] && kill "$pid" >/dev/null 2>&1 || true; done; }
  trap cleanup EXIT INT TERM

  log "Backend: http://localhost:${BACKEND_PORT}  (health /api/health · docs /docs)"
  PYTHONPATH="$REPO_ROOT/backend" "$VENV_PY" -m uvicorn skillopt_studio.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" --reload &
  PIDS+=("$!")

  if [ "$FRONTEND_READY" = "yes" ]; then
    log "Frontend: http://localhost:${FRONTEND_PORT}"
    ( cd "$REPO_ROOT/frontend" && npm run dev -- --port "$FRONTEND_PORT" ) &
    PIDS+=("$!")
  else
    warn "Frontend not started (deps missing). Backend only. See ./run.sh doctor."
  fi

  log "Up. Ctrl-C to stop."
  wait
}

case "$CMD" in
  doctor)  doctor ;;
  install) install ;;
  run)     launch ;;
  default) install; echo; launch ;;
esac
