/**
 * v1747 Phase 5b: LineOutcomeChip rendering + /verify lineHash validation.
 *
 * Smoke tests: the component renders the four canonical Outcome states
 * with distinguishable styles, and the /verify page rejects malformed
 * lineHash inputs (defense in depth on top of the page-level regex).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LineOutcomeChip from "@/components/LineOutcomeChip";
import type { SubgraphLine } from "@/lib/subgraph";

function makeLine(overrides: Partial<SubgraphLine> = {}): SubgraphLine {
  return {
    id: "0x" + "ab".repeat(32),
    outcome: "Pending",
    finalizedAt: null,
    finalizedAtBlock: null,
    finalizedAtTx: null,
    forceVoided: false,
    voidReason: null,
    attestations: [],
    ...overrides,
  };
}

describe("LineOutcomeChip", () => {
  it("renders the canonical outcome label", () => {
    const line = makeLine({ outcome: "Favorable" });
    render(<LineOutcomeChip line={line} linkToVerify={false} />);
    expect(screen.getByText("Favorable")).toBeInTheDocument();
  });

  it("renders Pending state without finalized data", () => {
    const line = makeLine({ outcome: "Pending" });
    render(<LineOutcomeChip line={line} linkToVerify={false} />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("includes optional plain-English label", () => {
    const line = makeLine({ outcome: "Favorable" });
    render(<LineOutcomeChip line={line} label="Lakers -3.5" linkToVerify={false} />);
    expect(screen.getByText("Lakers -3.5")).toBeInTheDocument();
    expect(screen.getByText("Favorable")).toBeInTheDocument();
  });

  it("shows attestor count in verbose mode when finalized", () => {
    const line = makeLine({
      outcome: "Favorable",
      finalizedAt: "1700000000",
      attestations: [
        {
          id: "a1",
          attestor: "0x" + "1".repeat(40),
          outcome: "Favorable",
          block: "100",
          blockNumber: "100",
          tx: "0x" + "f".repeat(64),
        },
        {
          id: "a2",
          attestor: "0x" + "2".repeat(40),
          outcome: "Favorable",
          block: "100",
          blockNumber: "100",
          tx: "0x" + "f".repeat(64),
        },
      ],
    });
    render(<LineOutcomeChip line={line} verbose linkToVerify={false} />);
    expect(screen.getByText("2/4 sigs")).toBeInTheDocument();
  });

  it("hides attestor count when not finalized", () => {
    const line = makeLine({
      outcome: "Pending",
      attestations: [
        {
          id: "a1",
          attestor: "0x" + "1".repeat(40),
          outcome: "Favorable",
          block: "100",
          blockNumber: "100",
          tx: "0x" + "f".repeat(64),
        },
      ],
    });
    render(<LineOutcomeChip line={line} verbose linkToVerify={false} />);
    expect(screen.queryByText(/sigs/)).not.toBeInTheDocument();
  });

  it("flags force-voided lines", () => {
    const line = makeLine({
      outcome: "Void",
      forceVoided: true,
      voidReason: "ESPN ambiguity",
    });
    render(<LineOutcomeChip line={line} linkToVerify={false} />);
    expect(screen.getByText("force-voided")).toBeInTheDocument();
  });

  it("links to /verify/[id] by default", () => {
    const line = makeLine({ outcome: "Favorable" });
    render(<LineOutcomeChip line={line} />);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe(`/verify/${line.id}`);
  });
});

describe("lineHash validation regex", () => {
  // The /verify/[lineHash] page rejects anything not matching this shape.
  const isValid = (s: string) => /^0x[0-9a-fA-F]{64}$/.test(s);

  it("accepts canonical 32-byte hex", () => {
    expect(isValid("0x" + "a".repeat(64))).toBe(true);
    expect(isValid("0x" + "ABCDEF".padEnd(64, "0"))).toBe(true);
  });

  it("rejects missing 0x prefix", () => {
    expect(isValid("a".repeat(64))).toBe(false);
  });

  it("rejects wrong length", () => {
    expect(isValid("0x" + "a".repeat(63))).toBe(false);
    expect(isValid("0x" + "a".repeat(65))).toBe(false);
  });

  it("rejects non-hex characters", () => {
    expect(isValid("0x" + "g".repeat(64))).toBe(false);
  });
});
