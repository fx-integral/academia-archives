import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

const mockEscrowPaused = vi.fn();
const mockCollateralPaused = vi.fn();
const mockCreditLedgerPaused = vi.fn();
const mockAccountPaused = vi.fn();
const mockSignalCommitmentPaused = vi.fn();
const mockAuditPaused = vi.fn();

vi.mock("../contracts", () => ({
  getEscrowContract: () => ({ paused: mockEscrowPaused }),
  getCollateralContract: () => ({ paused: mockCollateralPaused }),
  getCreditLedgerContract: () => ({ paused: mockCreditLedgerPaused }),
  getAccountContract: () => ({ paused: mockAccountPaused }),
  getSignalCommitmentContract: () => ({ paused: mockSignalCommitmentPaused }),
  getAuditContract: () => ({ paused: mockAuditPaused }),
  getUsdcContract: () => ({}),
  ADDRESSES: {},
}));

vi.mock("wagmi", () => ({
  useAccount: () => ({ address: undefined, chainId: undefined }),
  useWalletClient: () => ({ data: null }),
}));
vi.mock("@wagmi/core", () => ({
  waitForTransactionReceipt: vi.fn(),
  getBlockNumber: vi.fn(),
}));
vi.mock("../../app/providers", () => ({ wagmiConfig: {} }));

import { useProtocolPaused, useMutationGate } from "../hooks";

beforeEach(() => {
  vi.clearAllMocks();
  mockEscrowPaused.mockResolvedValue(false);
  mockCollateralPaused.mockResolvedValue(false);
  mockCreditLedgerPaused.mockResolvedValue(false);
  mockAccountPaused.mockResolvedValue(false);
  mockSignalCommitmentPaused.mockResolvedValue(false);
  mockAuditPaused.mockResolvedValue(false);
});

describe("useProtocolPaused", () => {
  it("reports anyPaused=false when no contract is paused", async () => {
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.anyPaused).toBe(false);
    expect(result.current.byContract).toEqual({
      escrow: false,
      collateral: false,
      creditLedger: false,
      account: false,
      signalCommitment: false,
      audit: false,
    });
  });

  it("reports anyPaused=true when SignalCommitment is paused (blocks new signal commits)", async () => {
    mockSignalCommitmentPaused.mockResolvedValue(true);
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.anyPaused).toBe(true);
    expect(result.current.byContract.signalCommitment).toBe(true);
    expect(result.current.byContract.escrow).toBe(false);
  });

  it("reports anyPaused=true when Audit is paused (blocks user early-exit)", async () => {
    mockAuditPaused.mockResolvedValue(true);
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.anyPaused).toBe(true);
    expect(result.current.byContract.audit).toBe(true);
  });

  it("reports anyPaused=true when Escrow is paused", async () => {
    mockEscrowPaused.mockResolvedValue(true);
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.anyPaused).toBe(true);
    expect(result.current.byContract.escrow).toBe(true);
    expect(result.current.byContract.collateral).toBe(false);
  });

  it("reports each contract independently when multiple are paused", async () => {
    mockEscrowPaused.mockResolvedValue(true);
    mockAccountPaused.mockResolvedValue(true);
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.byContract.escrow).toBe(true);
    expect(result.current.byContract.account).toBe(true);
    expect(result.current.byContract.collateral).toBe(false);
    expect(result.current.byContract.creditLedger).toBe(false);
  });

  it("treats read failure as not-paused so a broken paused() getter does not mask a real pause on another contract", async () => {
    mockEscrowPaused.mockRejectedValue(new Error("call failed"));
    mockCollateralPaused.mockResolvedValue(true);
    const { result } = renderHook(() => useProtocolPaused(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Escrow read failed => reported as false (fail-open for banner)
    expect(result.current.byContract.escrow).toBe(false);
    // Collateral paused => banner fires on its own
    expect(result.current.byContract.collateral).toBe(true);
    expect(result.current.anyPaused).toBe(true);
  });
});

describe("useMutationGate", () => {
  it("returns null when the named subsystem is not paused", async () => {
    mockEscrowPaused.mockResolvedValue(false);
    const { result } = renderHook(
      () => {
        const check = useMutationGate();
        const paused = useProtocolPaused();
        return { check, paused };
      },
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.paused.loading).toBe(false));
    expect(result.current.check("escrow", "Purchase")).toBeNull();
  });

  it("returns a user-facing error message when the named subsystem is paused", async () => {
    mockEscrowPaused.mockResolvedValue(true);
    const { result } = renderHook(
      () => {
        const check = useMutationGate();
        const paused = useProtocolPaused();
        return { check, paused };
      },
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.paused.loading).toBe(false));
    const err = result.current.check("escrow", "Purchase");
    expect(err).not.toBeNull();
    expect(err).toMatch(/Purchase/);
    expect(err).toMatch(/paused/i);
  });

  it("does not block a sibling subsystem when the requested one is healthy", async () => {
    mockEscrowPaused.mockResolvedValue(true); // escrow paused
    mockSignalCommitmentPaused.mockResolvedValue(false); // signal still live
    const { result } = renderHook(
      () => {
        const check = useMutationGate();
        const paused = useProtocolPaused();
        return { check, paused };
      },
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.paused.loading).toBe(false));
    // Gating commit-signal only looks at signalCommitment, so escrow pause
    // should not short-circuit the commit path.
    expect(result.current.check("signalCommitment", "Commit signal")).toBeNull();
    // But a purchase call that checks escrow should be blocked.
    expect(result.current.check("escrow", "Purchase")).not.toBeNull();
  });
});
