"""parse_line tests using the literal stdout lines generic_qa actually prints (#8).

generic_qa emits bare stage markers ("1/6 rollout") and per-item rollout lines
("    [rollout] id=<id> hard=<0|1> soft=<float>"). The runner must aggregate the
per-item soft scores into a step train_score at the gate boundary.
"""

from __future__ import annotations

from skillopt_studio.domain import StageEvent, StepEvent
from skillopt_studio.skillopt.runner import parse_line


def _feed(lines: list[str]):
    state: dict = {}
    out = []
    for ln in lines:
        out.extend(parse_line(ln, state))
    return out, state


class TestStageMarkers:
    def test_bare_stage_marker(self):
        events, _ = _feed(["1/6 rollout"])
        stages = [e for e in events if isinstance(e, StageEvent)]
        assert any(s.index == 1 and "rollout" in s.stage for s in stages)

    def test_bracketed_stage_marker(self):
        events, _ = _feed(["[4/6 SELECT]"])
        stages = [e for e in events if isinstance(e, StageEvent)]
        assert any(s.index == 4 and "select" in s.stage for s in stages)


class TestRolloutAggregation:
    def test_per_item_soft_aggregates_into_train_score(self):
        lines = [
            "[STEP 1/6]",
            "1/6 rollout",
            "    [rollout] id=a hard=1 soft=1.000",
            "    [rollout] id=b hard=0 soft=0.000",
            "    [rollout] id=c hard=1 soft=0.500",
            "[6/6 EVALUATE] ACCEPT (new best) soft=0.7",
        ]
        events, state = _feed(lines)
        # The accumulator holds the three soft values.
        assert state["rollout_softs"] == [1.0, 0.0, 0.5]
        # The gate StepEvent carries the aggregated train_score (mean = 0.5).
        gate_steps = [
            e for e in events
            if isinstance(e, StepEvent) and e.accepted is True
        ]
        assert gate_steps, "no gate StepEvent emitted"
        assert gate_steps[-1].train_score == 0.5
        assert gate_steps[-1].sel_score == 0.7

    def test_step_boundary_resets_accumulator(self):
        lines = [
            "[STEP 1/6]",
            "    [rollout] id=a hard=1 soft=1.000",
            "[STEP 2/6]",
            "    [rollout] id=b hard=0 soft=0.200",
        ]
        _events, state = _feed(lines)
        assert state["rollout_softs"] == [0.2]
        assert state["step"] == 2


class TestEpochAndStep:
    def test_epoch_and_step(self):
        events, state = _feed(["[EPOCH 2/4]", "[STEP 3/6]"])
        assert state["epoch"] == 2
        assert state["total_epochs"] == 4
        assert state["step"] == 3
        assert any(isinstance(e, StepEvent) for e in events)
