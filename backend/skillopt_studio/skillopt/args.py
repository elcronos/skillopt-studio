"""Build subprocess argv + env for SkillOpt's train.py / eval_only.py.

Two hard rules (see SKILLOPT_INTEGRATION.md):
1. **argv is a list, never a shell string** — the runner uses it with
   ``shell=False``. No value here is ever interpolated into a shell.
2. **Secrets travel via ``env`` only, NEVER argv** — API keys/endpoints are
   injected as environment variables (the exact names SkillOpt reads from
   ``.env.example``). Argv carries only the config path and non-secret
   ``--cfg-options section.key=value`` overrides, so process listings and logs
   never leak credentials.

Verified CLI shape:
    python scripts/train.py --config <yaml> [--cfg-options s.k=v s.k=v ...]
    python scripts/eval_only.py --config <yaml> --skill <skill.md> [--split S]

``--cfg-options`` is space-separated ``section.key=value`` (NOT individual flags).
Model selection lives in YAML (``model.*``); creds come from env. We therefore
keep argv overrides minimal and push model/backend choice through the generated
config + env, matching how the webui drives training.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

# Backend → ordered list of (skillopt env var name, ModelConfig attribute) the
# secret/endpoint values are sourced from. Verified against .env.example.
# Only NON-secret routing (endpoints/versions) plus the SECRET key are placed in
# env. The actual secret string is supplied by the caller (keyring), never here.
_BACKEND_ENV_KEYS: dict[str, list[str]] = {
    "openai_chat": [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_AUTH_MODE",
    ],
    # Azure OpenAI uses the same env namespace as openai_chat in SkillOpt.
    "azure_openai": [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_AUTH_MODE",
    ],
    "claude_chat": ["ANTHROPIC_API_KEY"],
    "qwen_chat": ["QWEN_CHAT_BASE_URL", "QWEN_CHAT_API_KEY", "QWEN_CHAT_MODEL"],
    "minimax_chat": ["MINIMAX_BASE_URL", "MINIMAX_API_KEY", "MINIMAX_MODEL"],
}

# Env var names that hold SECRETS — never logged, never argv.
SECRET_ENV_KEYS: frozenset[str] = frozenset({
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "QWEN_CHAT_API_KEY",
    "MINIMAX_API_KEY",
    "OPTIMIZER_AZURE_OPENAI_API_KEY",
    "TARGET_AZURE_OPENAI_API_KEY",
    "OPTIMIZER_MINIMAX_API_KEY",
    "TARGET_MINIMAX_API_KEY",
})


def _train_script(skillopt_clone_dir: str | Path) -> str:
    return str(Path(skillopt_clone_dir) / "scripts" / "train.py")


def _eval_script(skillopt_clone_dir: str | Path) -> str:
    return str(Path(skillopt_clone_dir) / "scripts" / "eval_only.py")


def build_train_argv(
    config_path: str | Path,
    skillopt_clone_dir: str | Path,
    cfg_options: Mapping[str, Any] | None = None,
    python_executable: str | None = None,
) -> list[str]:
    """Return the argv list for ``scripts/train.py``.

    ``cfg_options`` maps ``"section.key"`` → value and is rendered as
    ``--cfg-options section.key=value ...`` (space-separated). No secrets belong
    in ``cfg_options``.
    """
    py = python_executable or sys.executable
    argv = [py, _train_script(skillopt_clone_dir), "--config", str(config_path)]
    opts = _render_cfg_options(cfg_options)
    if opts:
        argv.append("--cfg-options")
        argv.extend(opts)
    return argv


def build_eval_argv(
    config_path: str | Path,
    skill_path: str | Path,
    skillopt_clone_dir: str | Path,
    split: str = "test",
    cfg_options: Mapping[str, Any] | None = None,
    python_executable: str | None = None,
) -> list[str]:
    """Return the argv list for ``scripts/eval_only.py``."""
    py = python_executable or sys.executable
    argv = [
        py,
        _eval_script(skillopt_clone_dir),
        "--config",
        str(config_path),
        "--skill",
        str(skill_path),
    ]
    if split:
        argv += ["--split", str(split)]
    opts = _render_cfg_options(cfg_options)
    if opts:
        argv.append("--cfg-options")
        argv.extend(opts)
    return argv


def _render_cfg_options(cfg_options: Mapping[str, Any] | None) -> list[str]:
    if not cfg_options:
        return []
    rendered: list[str] = []
    for key, value in cfg_options.items():
        k = str(key).strip()
        if not k:
            continue
        if any(s in k.upper() for s in ("API_KEY", "SECRET", "TOKEN", "PASSWORD")):
            raise ValueError(f"refusing to place secret-looking key {k!r} in argv")
        rendered.append(f"{k}={_fmt_value(value)}")
    return rendered


def _fmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _inject_backend_secret(env: dict[str, str], backend: str, secret: str, prefix: str = "") -> None:
    """Inject *secret* into *env* under the env var(s) *backend* reads.

    ``prefix`` is ``""`` for the shared/base key, ``"OPTIMIZER_"`` or ``"TARGET_"``
    for per-role keys (verified against ``.env.example``: SkillOpt reads
    ``OPTIMIZER_AZURE_OPENAI_API_KEY`` / ``TARGET_AZURE_OPENAI_API_KEY`` and
    falls back to the shared ``AZURE_OPENAI_API_KEY`` when a role override is
    unset — mirroring the webui propagation).
    """
    if not secret:
        return
    if backend in ("openai_chat", "openai_compatible", "azure_openai"):
        env[f"{prefix}AZURE_OPENAI_API_KEY"] = secret
    elif backend == "claude_chat":
        # Anthropic has no per-role env namespace; the shared key is used.
        env["ANTHROPIC_API_KEY"] = secret
    elif backend == "qwen_chat":
        env["QWEN_CHAT_API_KEY"] = secret
    elif backend == "minimax_chat":
        env[f"{prefix}MINIMAX_API_KEY" if prefix else "MINIMAX_API_KEY"] = secret


def build_model_env(
    model_config: Any,
    secret: str | None = None,
    base_env: Mapping[str, str] | None = None,
    optimizer_secret: str | None = None,
    target_secret: str | None = None,
) -> dict[str, str]:
    """Build the subprocess environment dict from a ``ModelConfig``-like object.

    Reads attributes ``backend``, ``optimizer_backend``, ``target_backend``,
    ``endpoint``, ``api_version`` from *model_config* (duck-typed so a pydantic
    model or a plain dict-wrapped object both work). ``PYTHONUNBUFFERED=1`` is
    always set so the runner sees stdout line-by-line.

    Secrets (all from keyring, never argv/logs) are injected as env vars:
    - *secret* — the shared/base key for ``model.backend`` (back-compat).
    - *optimizer_secret* — keyed under the OPTIMIZER role for
      ``optimizer_backend`` (e.g. ``OPTIMIZER_AZURE_OPENAI_API_KEY``).
    - *target_secret* — keyed under the TARGET role for ``target_backend``
      (e.g. ``TARGET_AZURE_OPENAI_API_KEY``).
    When a role secret is absent the shared key is left to cover it (SkillOpt
    inherits the base key when a role override is unset).

    The returned dict is suitable to pass to ``subprocess.Popen(env=...)``;
    never log it verbatim — use :func:`redact_env`.
    """
    env: dict[str, str] = dict(base_env or {})
    env["PYTHONUNBUFFERED"] = "1"

    backend = _attr(model_config, "backend", "openai_chat") or "openai_chat"
    optimizer_backend = _attr(model_config, "optimizer_backend", None) or backend
    target_backend = _attr(model_config, "target_backend", None) or backend
    endpoint = _attr(model_config, "endpoint", None)
    api_version = _attr(model_config, "api_version", None)

    # Non-secret routing (endpoints/versions) under the shared namespace.
    if backend in ("openai_chat", "openai_compatible", "azure_openai"):
        if endpoint:
            env["AZURE_OPENAI_ENDPOINT"] = str(endpoint)
        if api_version:
            env["AZURE_OPENAI_API_VERSION"] = str(api_version)
    elif backend == "qwen_chat":
        if endpoint:
            env["QWEN_CHAT_BASE_URL"] = str(endpoint)
    elif backend == "minimax_chat":
        if endpoint:
            env["MINIMAX_BASE_URL"] = str(endpoint)

    # Shared/base secret (back-compat single-key path).
    if secret:
        _inject_backend_secret(env, backend, secret)
    # Per-role secrets (preferred). These take precedence for their role and
    # cover the case where optimizer/target use different backends.
    if optimizer_secret:
        _inject_backend_secret(env, optimizer_backend, optimizer_secret, prefix="OPTIMIZER_")
    if target_secret:
        _inject_backend_secret(env, target_backend, target_secret, prefix="TARGET_")

    return env


def _attr(obj: Any, name: str, default: Any) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of *env* with secret values masked, safe for logging."""
    out: dict[str, str] = {}
    for k, v in env.items():
        if k in SECRET_ENV_KEYS or any(s in k.upper() for s in ("API_KEY", "SECRET", "TOKEN", "PASSWORD")):
            out[k] = "***REDACTED***" if v else ""
        else:
            out[k] = v
    return out


def backend_env_keys(backend: str) -> list[str]:
    """Return the env var names SkillOpt reads for *backend* (for docs/validation)."""
    return list(_BACKEND_ENV_KEYS.get(backend, []))


__all__ = [
    "build_train_argv",
    "build_eval_argv",
    "build_model_env",
    "redact_env",
    "backend_env_keys",
    "SECRET_ENV_KEYS",
]
