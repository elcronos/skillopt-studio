"""Central configuration: filesystem paths, ports, and Python-version helpers.

All paths are derived from the repository root so the studio behaves identically
regardless of the current working directory. Nothing here performs I/O at import
time beyond resolving paths; directory creation is opt-in via ``ensure_dirs()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# --- Repository layout -------------------------------------------------------
# This file lives at: <repo>/backend/skillopt_studio/config.py
# parents[0] = skillopt_studio, [1] = backend, [2] = repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

BACKEND_DIR: Path = REPO_ROOT / "backend"
PACKAGE_DIR: Path = BACKEND_DIR / "skillopt_studio"

# Virtualenv created/reused by run.sh.
VENV_DIR: Path = REPO_ROOT / ".venv"
VENV_PYTHON: Path = VENV_DIR / "bin" / "python"

# SkillOpt is installed editable into the venv via `pip install -e git+...`.
# pip's default editable checkout location for a git source is <venv>/src/<egg>.
SKILLOPT_CLONE_DIR: Path = VENV_DIR / "src" / "skillopt"

# Runtime / user-data directories (gitignored).
OUTPUTS_DIR: Path = REPO_ROOT / "outputs"          # SkillOpt run trees: outputs/<env>/<run>/
CONFIGS_DIR: Path = REPO_ROOT / "configs"          # generated configs: configs/generic_qa/<slug>.yaml
FIXTURES_DIR: Path = REPO_ROOT / "tests" / "fixtures"
GOLDEN_RUN_DIR: Path = FIXTURES_DIR / "golden_run"

# Reference material copied verbatim from SkillOpt (read-only contract).
REFERENCE_DIR: Path = REPO_ROOT / "reference"

# Graph sidecar (Node).
GRAPH_SIDECAR_DIR: Path = REPO_ROOT / "graph-sidecar"

# --- SkillOpt pin ------------------------------------------------------------
SKILLOPT_REPO_URL: str = "https://github.com/microsoft/SkillOpt"
SKILLOPT_PINNED_SHA: str = "8ebede0efdb69f6b74472fc8ad009f716bb4ca1b"

# --- skill-to-langgraph companion ("Convert to LangGraph" feature) -----------
# The companion converter is a separate skill repo. Its location is overridable
# via env so the studio is not pinned to one checkout. Existence is checked at
# call time (NOT import) so the conversions router still mounts if it is absent.
import os as _os  # noqa: E402

LANGGRAPH_SKILL_DIR: Path = Path(
    _os.environ.get("SKILLOPT_LANGGRAPH_DIR", str(Path.home() / "Desktop" / "skill-to-langgraph"))
).expanduser()
LANGGRAPH_VENV_PYTHON: Path = LANGGRAPH_SKILL_DIR / ".venv" / "bin" / "python"

# --- Ports -------------------------------------------------------------------
BACKEND_HOST: str = "127.0.0.1"
BACKEND_PORT: int = 8000
FRONTEND_PORT: int = 5173
FRONTEND_ORIGIN: str = f"http://localhost:{FRONTEND_PORT}"

# CORS origins allowed in dev (both localhost and 127.0.0.1 spellings).
CORS_ORIGINS: tuple[str, ...] = (
    f"http://localhost:{FRONTEND_PORT}",
    f"http://127.0.0.1:{FRONTEND_PORT}",
)

# --- Python version policy ---------------------------------------------------
# run.sh enforces this; helpers here let the backend self-report and warn.
MIN_PYTHON: tuple[int, int] = (3, 10)
MAX_PYTHON_EXCLUSIVE: tuple[int, int] = (3, 14)  # >=3.10, <3.14


def python_version_string() -> str:
    """Return the running interpreter version as ``"X.Y.Z"``."""
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def python_version_supported(version: tuple[int, int, int] | None = None) -> bool:
    """Return True when ``version`` (default: current) is >=3.10 and <3.14."""
    if version is None:
        v = sys.version_info
        version = (v.major, v.minor, v.micro)
    major_minor = (version[0], version[1])
    return MIN_PYTHON <= major_minor < MAX_PYTHON_EXCLUSIVE


def ensure_dirs() -> None:
    """Create the user-data directories the studio writes to (idempotent)."""
    for d in (OUTPUTS_DIR, CONFIGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
