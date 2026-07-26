"""HTTP-boundary tests for the grader advisory endpoints.

These assert the EXACT JSON keys the frontend consumes (api.ts GraderRecommendation
{type, rationale} and GraderEstimate {calls, note}). They exist to catch cross-stack
shape drift that the per-function unit tests + TypeScript cannot see, per the
re-validation finding on /api/graders/recommend and /api/graders/estimate-cost.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from skillopt_studio.main import app

client = TestClient(app)

_DATASET = {
    "name": "http-grader-fixture",
    "split_mode": "ratio",
    "split_ratio": "2:1:7",
    "cases": [
        {"id": "a", "input": "What is 2+2?", "ground_truth": "4", "metadata": {}},
        {"id": "b", "input": "Capital of France?", "ground_truth": "Paris", "metadata": {}},
        {
            "id": "c",
            "input": "Summarize the plot.",
            "ground_truth": "A long free-text answer spanning multiple sentences about the story.",
            "metadata": {},
        },
    ],
}


def _ensure_dataset() -> str:
    client.delete(f"/api/datasets/{_DATASET['name']}")
    resp = client.post("/api/datasets", json=_DATASET)
    assert resp.status_code in (200, 201), resp.text
    return _DATASET["name"]


def test_recommend_returns_type_and_rationale_keys() -> None:
    name = _ensure_dataset()
    try:
        resp = client.get("/api/graders/recommend", params={"dataset": name})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Frontend reads rec.type and rec.rationale (api.ts GraderRecommendation).
        assert "type" in body, f"missing 'type' key: {body}"
        assert "rationale" in body, f"missing 'rationale' key: {body}"
        assert isinstance(body["type"], str) and body["type"]
    finally:
        client.delete(f"/api/datasets/{name}")


def test_estimate_cost_returns_calls_key() -> None:
    name = _ensure_dataset()
    try:
        resp = client.get(
            "/api/graders/estimate-cost",
            params={"dataset": name, "num_epochs": 2, "self_consistency": 1},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Frontend reads estimate.calls and estimate.note (api.ts GraderEstimate).
        assert "calls" in body, f"missing 'calls' key: {body}"
        assert isinstance(body["calls"], int)
    finally:
        client.delete(f"/api/datasets/{name}")


def test_recommend_unknown_dataset_404() -> None:
    resp = client.get("/api/graders/recommend", params={"dataset": "does-not-exist-xyz"})
    assert resp.status_code == 404
