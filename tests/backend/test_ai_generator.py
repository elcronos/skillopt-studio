"""Tests for the AI-generation helpers + /api/ai endpoints.

The real ``claude`` CLI is NEVER invoked: ``ai.claude_cli._run_claude`` is
monkeypatched to return canned model text (including ```json-fenced and
prose-wrapped variants to exercise ``_extract_json``). HTTP-boundary tests assert
the JSON shapes the frontend consumes and that a ClaudeCLIError maps to 503.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from skillopt_studio.ai import claude_cli
from skillopt_studio.ai.claude_cli import (
    ClaudeCLIError,
    _extract_json,
    generate_custom_scorer,
    generate_dataset_cases,
    generate_geval_criteria,
)
from skillopt_studio.main import app

client = TestClient(app)


# --- _extract_json ----------------------------------------------------------
def test_extract_json_plain() -> None:
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced() -> None:
    text = 'Sure! Here you go:\n```json\n[{"id": "x"}]\n```\nThanks.'
    assert _extract_json(text) == [{"id": "x"}]


def test_extract_json_prose_wrapped() -> None:
    text = 'Here is the object you asked for: {"k": [1, 2]} — enjoy.'
    assert _extract_json(text) == {"k": [1, 2]}


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(ClaudeCLIError):
        _extract_json("no json here at all")


# --- generators (monkeypatched _run_claude) ---------------------------------
def test_generate_dataset_cases_parses_and_validates(monkeypatch) -> None:
    canned = (
        '```json\n'
        '[{"id": "c1", "input": "Q1?", "ground_truth": "A1", "metadata": {"t": 1}},'
        ' {"input": "Q2?", "ground_truth": "A2"}]\n'
        '```'
    )
    monkeypatch.setattr(claude_cli, "_run_claude", lambda *a, **k: canned)
    cases = generate_dataset_cases("skill body", "test it", count=10)
    assert len(cases) == 2
    assert cases[0]["id"] == "c1"
    assert cases[0]["metadata"] == {"t": 1}
    # Missing id gets auto-assigned.
    assert cases[1]["id"] == "case_2"
    assert cases[1]["input"] == "Q2?"


def test_generate_dataset_cases_clamps_count(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake(prompt: str, **k):
        captured["prompt"] = prompt
        return '[{"id": "c1", "input": "x", "ground_truth": "y"}]'

    monkeypatch.setattr(claude_cli, "_run_claude", fake)
    generate_dataset_cases("body", "instr", count=999)
    assert "exactly 50" in captured["prompt"]


def test_generate_geval_criteria_parses(monkeypatch) -> None:
    canned = (
        'Here are the criteria:\n'
        '{"criteria": [{"name": "Faithfulness", "description": "stays true"}],'
        ' "evaluation_steps": ["read", "compare", "score"]}'
    )
    monkeypatch.setattr(claude_cli, "_run_claude", lambda *a, **k: canned)
    out = generate_geval_criteria("body", "judge faithfulness")
    assert out["criteria"] == [{"name": "Faithfulness", "description": "stays true"}]
    assert out["evaluation_steps"] == ["read", "compare", "score"]


def test_generate_custom_scorer_parses_and_adds_header(monkeypatch) -> None:
    code = "def score(prediction, ground_truth, item=None):\\n    return 1.0"
    canned = '{"custom_code": "' + code + '"}'
    monkeypatch.setattr(claude_cli, "_run_claude", lambda *a, **k: canned)
    out = generate_custom_scorer("body", "exact match")
    assert "custom_code" in out
    assert "AI-DRAFTED" in out["custom_code"]
    assert "def score(prediction, ground_truth, item=None)" in out["custom_code"]


# --- HTTP boundary ----------------------------------------------------------
def test_available_endpoint_shape() -> None:
    resp = client.get("/api/ai/available")
    assert resp.status_code == 200
    body = resp.json()
    assert "available" in body and isinstance(body["available"], bool)


def test_generate_dataset_http_success(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_cli,
        "_run_claude",
        lambda *a, **k: '[{"id": "c1", "input": "Q", "ground_truth": "A"}]',
    )
    resp = client.post(
        "/api/ai/generate-dataset",
        json={"skill_body": "a skill", "instruction": "test", "count": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cases"][0]["id"] == "c1"


def test_cli_error_maps_to_503(monkeypatch) -> None:
    def boom(*a, **k):
        raise ClaudeCLIError("claude not found")

    monkeypatch.setattr(claude_cli, "_run_claude", boom)
    resp = client.post(
        "/api/ai/generate-geval",
        json={"skill_body": "a skill", "instruction": "x"},
    )
    assert resp.status_code == 503
    assert "claude CLI not available" in resp.json()["detail"]


def test_unknown_skill_id_404() -> None:
    resp = client.post(
        "/api/ai/generate-scorer",
        json={"skill_id": "claude:does-not-exist-xyz", "instruction": "x"},
    )
    assert resp.status_code == 404
