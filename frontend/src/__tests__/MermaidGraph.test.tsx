import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MermaidGraph from "../components/MermaidGraph";

// Mock the mermaid lib: render() returns a deterministic SVG so the test runs
// without a real layout engine. We assert the component injects what mermaid
// hands back, and that the {error, rawMarkdown} fallback path renders raw text.
vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (_id: string, src: string) => ({
      svg: `<svg data-src="${src.length}"><g class="node" id="A">A</g></svg>`,
    })),
  },
}));

describe("MermaidGraph", () => {
  it("renders an SVG from a mermaid string", async () => {
    render(<MermaidGraph mermaidText={"graph TD\n  A-->B"} />);
    await waitFor(() => {
      const wrap = screen.getByTestId("mermaid-svg");
      expect(wrap.querySelector("svg")).toBeTruthy();
    });
  });

  it("shows cross-reference chips with →N / ←M counts", async () => {
    render(
      <MermaidGraph
        mermaidText={"graph TD\n  A-->B"}
        crossRefs={{ A: { forward: 3, back: 1 } }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/→3/)).toBeInTheDocument();
      expect(screen.getByText(/←1/)).toBeInTheDocument();
    });
  });

  it("falls back to raw markdown when the backend reports an error", () => {
    render(
      <MermaidGraph
        graph={{ error: "no graph block", rawMarkdown: "# raw skill body" }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/extraction failed/i);
    expect(screen.getByText(/raw skill body/)).toBeInTheDocument();
  });
});
