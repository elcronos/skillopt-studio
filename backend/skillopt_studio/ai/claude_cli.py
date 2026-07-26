"""Thin wrapper around the local ``claude`` CLI for drafting studio artifacts.

Invocation is non-interactive and argv-based (NEVER ``shell=True``)::

    claude -p "<prompt>" --output-format json

The CLI prints a JSON envelope whose ``.result`` field holds the model's text.
We instruct the model to emit STRICT JSON only; we then parse ``.result`` and
robustly extract the first JSON object/array from it (tolerating ```json fences
and leading prose).

Everything here DRAFTS content for review. Generated custom-scorer code is never
executed in this module; it is returned as text for the user to inspect and, only
on an explicit consented run, route through the existing honest-mistake sandbox.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any

from ..domain import DatasetCase

logger = logging.getLogger("skillopt_studio.ai.claude_cli")

# Optional override so deployments can pin a specific binary; otherwise PATH.
_CLAUDE_BIN_ENV = "SKILLOPT_CLAUDE_BIN"

# Keep prompts focused: truncate very long skill bodies to a sane limit so we do
# not blow the CLI argv / context. The skill's intent is captured well before this.
_MAX_SKILL_CHARS = 12_000

_DATASET_COUNT_MIN = 1
_DATASET_COUNT_MAX = 50


class ClaudeCLIError(RuntimeError):
    """Raised when the ``claude`` CLI is missing, errors, times out, or returns
    output we cannot parse."""


def _claude_bin() -> str | None:
    """Resolve the claude binary: explicit env override, else PATH lookup."""
    override = os.environ.get(_CLAUDE_BIN_ENV)
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        # An override that names a binary on PATH is also acceptable.
        resolved = shutil.which(override)
        if resolved:
            return resolved
        return None
    return shutil.which("claude")


def claude_available() -> bool:
    """Return True when a usable ``claude`` binary can be resolved."""
    return _claude_bin() is not None


def _run_claude(prompt: str, *, timeout: int = 180) -> str:
    """Run ``claude -p <prompt> --output-format json`` and return ``.result``.

    Uses an argv LIST (no shell). Raises :class:`ClaudeCLIError` on a missing
    binary, non-zero exit, timeout, or an unparseable / malformed envelope.
    """
    claude_bin = _claude_bin()
    if claude_bin is None:
        raise ClaudeCLIError(
            "claude CLI not available (not found on PATH; set "
            f"{_CLAUDE_BIN_ENV} to override)."
        )

    argv = [claude_bin, "-p", prompt, "--output-format", "json"]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCLIError(f"claude CLI timed out after {timeout}s") from exc
    except OSError as exc:
        raise ClaudeCLIError(f"claude CLI could not be executed: {exc}") from exc

    if proc.returncode != 0:
        # Keep logs terse; do not echo the full prompt.
        err = (proc.stderr or "").strip()[-500:]
        raise ClaudeCLIError(
            f"claude CLI exited {proc.returncode}: {err or '(no stderr)'}"
        )

    out = (proc.stdout or "").strip()
    if not out:
        raise ClaudeCLIError("claude CLI returned empty output")
    try:
        envelope = json.loads(out)
    except json.JSONDecodeError as exc:
        raise ClaudeCLIError(f"claude CLI output was not valid JSON: {exc}") from exc

    result = envelope.get("result") if isinstance(envelope, dict) else None
    if not isinstance(result, str):
        raise ClaudeCLIError(
            "claude CLI envelope missing a string '.result' field"
        )
    return result


# --- JSON extraction --------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of model text.

    Handles ```json fenced blocks and leading/trailing prose. Raises
    :class:`ClaudeCLIError` if nothing parseable is found.
    """
    if not isinstance(text, str) or not text.strip():
        raise ClaudeCLIError("empty model result; no JSON to extract")

    candidates: list[str] = []

    # 1) Fenced code blocks first (most reliable).
    for match in _FENCE_RE.finditer(text):
        inner = match.group(1).strip()
        if inner:
            candidates.append(inner)

    # 2) The whole string (in case it is already pure JSON).
    candidates.append(text.strip())

    # 3) The first balanced object/array span anywhere in the text.
    span = _first_json_span(text)
    if span is not None:
        candidates.append(span)

    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue

    raise ClaudeCLIError("could not extract JSON from model result")


def _first_json_span(text: str) -> str | None:
    """Return the first balanced ``{...}`` or ``[...]`` substring, or None.

    Scans for the earliest opening brace/bracket and walks to its match,
    ignoring braces inside double-quoted strings (with escape handling).
    """
    start = None
    opener = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            break
    if start is None:
        return None

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    return None


def _truncate_skill(skill_body: str) -> str:
    body = (skill_body or "").strip()
    if len(body) <= _MAX_SKILL_CHARS:
        return body
    return body[:_MAX_SKILL_CHARS] + "\n...[truncated]..."


# --- Generators -------------------------------------------------------------
def generate_dataset_cases(
    skill_body: str, instruction: str, count: int = 10
) -> list[dict[str, Any]]:
    """Draft ``count`` dataset cases that exercise the skill per ``instruction``.

    Returns a list of validated ``{id,input,ground_truth,metadata}`` dicts. Ids
    are assigned when missing; ``count`` is clamped to ``[1, 50]``.
    """
    n = max(_DATASET_COUNT_MIN, min(_DATASET_COUNT_MAX, int(count)))
    skill = _truncate_skill(skill_body)
    prompt = (
        "You are generating evaluation test cases for a skill that will be "
        "optimized. Produce a dataset that tests the skill according to the "
        "instruction.\n\n"
        f"SKILL BODY:\n{skill}\n\n"
        f"INSTRUCTION: {instruction}\n\n"
        f"Produce exactly {n} test cases. Output STRICT JSON ONLY (no prose, no "
        "markdown) as an array of objects, each with these fields:\n"
        '  "id": a short unique string identifier,\n'
        '  "input": the prompt/question given to the skill (string),\n'
        '  "ground_truth": the expected/ideal answer (string, may be empty for '
        "open-ended cases),\n"
        '  "metadata": an object of extra tags (may be empty {}).\n'
        f"Return ONLY the JSON array of {n} objects."
    )
    raw = _run_claude(prompt)
    data = _extract_json(raw)
    if isinstance(data, dict):
        # Tolerate {"cases": [...]} wrapping.
        data = data.get("cases", data)
    if not isinstance(data, list):
        raise ClaudeCLIError("expected a JSON array of dataset cases")

    cases: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        case_id = str(raw_id).strip() if raw_id not in (None, "") else f"case_{idx + 1}"
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        try:
            case = DatasetCase(
                id=case_id,
                input=str(item.get("input", "")),
                ground_truth=str(item.get("ground_truth", "") or ""),
                metadata=meta,
            )
        except Exception:  # noqa: BLE001 - skip a malformed case rather than fail all
            logger.warning("skipping a malformed generated case at index %d", idx)
            continue
        cases.append(case.model_dump())

    if not cases:
        raise ClaudeCLIError("no valid dataset cases were generated")
    return cases


def generate_geval_criteria(skill_body: str, instruction: str) -> dict[str, Any]:
    """Draft G-Eval criteria + evaluation steps suited to the skill's intent.

    Returns ``{"criteria": [{"name", "description"}, ...],
    "evaluation_steps": [str, ...]}``.
    """
    skill = _truncate_skill(skill_body)
    prompt = (
        "You are drafting DeepEval G-Eval grading criteria for evaluating the "
        "outputs of a skill.\n\n"
        f"SKILL BODY:\n{skill}\n\n"
        f"INSTRUCTION: {instruction}\n\n"
        "Output STRICT JSON ONLY (no prose, no markdown) as an object with:\n"
        '  "criteria": an array of objects, each {"name": short label, '
        '"description": what that criterion measures},\n'
        '  "evaluation_steps": an array of strings, the ordered steps a judge '
        "should follow to assign a 0..1 score.\n"
        "Return ONLY that JSON object."
    )
    raw = _run_claude(prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ClaudeCLIError("expected a JSON object with criteria/evaluation_steps")

    criteria_out: list[dict[str, str]] = []
    for c in data.get("criteria", []) or []:
        if isinstance(c, dict):
            name = str(c.get("name", "")).strip()
            desc = str(c.get("description", "")).strip()
        elif isinstance(c, str):
            name, desc = c.strip(), ""
        else:
            continue
        if name or desc:
            criteria_out.append({"name": name, "description": desc})

    steps_out = [
        str(s).strip()
        for s in (data.get("evaluation_steps", []) or [])
        if str(s).strip()
    ]

    if not criteria_out and not steps_out:
        raise ClaudeCLIError("no G-Eval criteria or evaluation steps were generated")
    return {"criteria": criteria_out, "evaluation_steps": steps_out}


def generate_custom_scorer(skill_body: str, instruction: str) -> dict[str, str]:
    """Draft a Python scorer matching the sandbox contract.

    The sandbox (grading/custom.py + sandbox.py) execs the user code and calls::

        def score(prediction: str, ground_truth: str, item: dict | None = None) -> float

    returning a float in ``[0, 1]``. We return ``{"custom_code": str}``; the code
    is NOT executed here — it is drafted for review and only ever runs later via
    the existing consented sandbox path.
    """
    skill = _truncate_skill(skill_body)
    prompt = (
        "You are drafting a Python scoring function for evaluating a skill's "
        "outputs. The function will run in a sandbox that calls it as:\n"
        "    score(prediction, ground_truth, item)\n"
        "where prediction is the skill's output string, ground_truth is the "
        "expected answer string, and item is a dict (or None) of the dataset "
        "case ({id,input,ground_truth,metadata}). It MUST be named exactly "
        "`score`, take exactly those three parameters (the third with a default "
        "of None), and return a float in [0, 1].\n\n"
        f"SKILL BODY:\n{skill}\n\n"
        f"INSTRUCTION: {instruction}\n\n"
        "Output STRICT JSON ONLY (no prose, no markdown) as an object with a "
        'single key "custom_code" whose value is the full Python source of the '
        "scorer (use \\n for newlines). Use only the Python standard library. "
        "Return ONLY that JSON object."
    )
    raw = _run_claude(prompt)
    data = _extract_json(raw)
    if isinstance(data, dict):
        code = data.get("custom_code") or data.get("code")
    elif isinstance(data, str):
        code = data
    else:
        code = None
    if not isinstance(code, str) or not code.strip():
        raise ClaudeCLIError("no custom scorer code was generated")

    header = (
        "# AI-DRAFTED scorer — REVIEW before use. Not executed server-side except\n"
        "# via the consented honest-mistake sandbox. Contract: score(prediction,\n"
        "# ground_truth, item=None) -> float in [0, 1].\n"
    )
    code = code.strip()
    if not code.startswith("#"):
        code = header + code
    else:
        code = header + code
    return {"custom_code": code}


__all__ = [
    "ClaudeCLIError",
    "claude_available",
    "generate_dataset_cases",
    "generate_geval_criteria",
    "generate_custom_scorer",
]
