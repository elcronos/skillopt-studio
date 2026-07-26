import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DatasetEditor from "../components/DatasetEditor";
import { api, type Dataset } from "../lib/api";

const DATASET: Dataset = {
  name: "ds",
  cases: [{ id: "c1", input: "in", ground_truth: "gt", metadata: {} }],
  split_mode: "ratio",
  split_ratio: "2:1:7",
};

afterEach(() => vi.restoreAllMocks());

describe("DatasetEditor AI control", () => {
  it("shows the AI panel when the claude CLI is available", async () => {
    vi.spyOn(api, "aiAvailable").mockResolvedValue(true);
    render(<DatasetEditor dataset={DATASET} onChange={() => {}} />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-dataset-panel")).toBeInTheDocument(),
    );
  });

  it("hides the AI panel when the claude CLI is unavailable", async () => {
    vi.spyOn(api, "aiAvailable").mockResolvedValue(false);
    render(<DatasetEditor dataset={DATASET} onChange={() => {}} />);
    // Give the availability probe a tick to resolve, then assert absence.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId("ai-dataset-panel")).not.toBeInTheDocument();
  });
});
