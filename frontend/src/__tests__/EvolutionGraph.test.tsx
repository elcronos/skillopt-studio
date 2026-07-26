import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EvolutionGraph from "../components/EvolutionGraph";
import type { ScorePoint } from "../lib/api";

const SAMPLE: ScorePoint[] = [
  { step: 0, epoch: 0, train_score: 0.42, sel_score: 0.4, accepted: false },
  { step: 1, epoch: 0, train_score: 0.55, sel_score: 0.51, accepted: true },
  { step: 2, epoch: 1, train_score: 0.63, sel_score: 0.6, accepted: true },
  { step: 3, epoch: 1, train_score: 0.61, sel_score: 0.58, accepted: false },
];

describe("EvolutionGraph", () => {
  it("binds a sample score series and renders the chart + telemetry", () => {
    render(<EvolutionGraph series={SAMPLE} connState="open" totalSteps={10} />);

    expect(screen.getByTestId("evolution-graph")).toBeInTheDocument();
    expect(screen.getByTestId("evo-chart")).toBeInTheDocument();

    // best gate score = max sel_score = 0.60
    expect(screen.getByText("0.600")).toBeInTheDocument();
    // connection badge reflects live state
    expect(screen.getByText("open")).toBeInTheDocument();
  });

  it("renders one gate tick per step", () => {
    const { container } = render(<EvolutionGraph series={SAMPLE} />);
    const ticks = container.querySelectorAll(".gate-tick");
    expect(ticks).toHaveLength(SAMPLE.length);
    // accepted -> .accept, rejected -> .reject
    expect(container.querySelectorAll(".gate-tick.accept")).toHaveLength(2);
    expect(container.querySelectorAll(".gate-tick.reject")).toHaveLength(2);
  });

  it("highlights the active stage in the six-stage pipeline", () => {
    render(<EvolutionGraph series={SAMPLE} currentStage={3} />);
    const pipeline = screen.getByTestId("pipeline");
    expect(pipeline.querySelectorAll(".stage-pill")).toHaveLength(6);
    expect(pipeline.querySelectorAll(".stage-pill.active")).toHaveLength(1);
    expect(pipeline.querySelectorAll(".stage-pill.done")).toHaveLength(2);
  });

  it("shows a waiting state with an empty series", () => {
    render(<EvolutionGraph series={[]} />);
    expect(screen.getByText(/Waiting for the first step/i)).toBeInTheDocument();
  });
});
