import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const mockUseAccount = vi.fn();
vi.mock("wagmi", () => ({
  useAccount: () => mockUseAccount(),
}));

import {
  useBookPreferences,
  ALL_BOOK_KEYS,
} from "../../components/BookPreferences";

const ADDR_A = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
const ADDR_B = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB";

function storageKey(addr: string) {
  return `djinn:books:${addr.toLowerCase()}`;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

describe("useBookPreferences", () => {
  it("defaults to all books when no wallet is connected", () => {
    mockUseAccount.mockReturnValue({ address: undefined });
    const { result } = renderHook(() => useBookPreferences());
    const [books] = result.current;
    expect(books).toEqual([...ALL_BOOK_KEYS]);
  });

  it("defaults to all books for a fresh wallet with no saved prefs", async () => {
    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result } = renderHook(() => useBookPreferences());
    await waitFor(() => expect(result.current[0]).toEqual([...ALL_BOOK_KEYS]));
  });

  it("loads saved prefs for a wallet", async () => {
    localStorage.setItem(storageKey(ADDR_A), JSON.stringify(["draftkings", "fanduel"]));
    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result } = renderHook(() => useBookPreferences());
    await waitFor(() => expect(result.current[0]).toEqual(["draftkings", "fanduel"]));
  });

  it("persists updates to localStorage for the current wallet", () => {
    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result } = renderHook(() => useBookPreferences());
    act(() => {
      result.current[1](["bet365"]);
    });
    expect(result.current[0]).toEqual(["bet365"]);
    expect(localStorage.getItem(storageKey(ADDR_A))).toBe(JSON.stringify(["bet365"]));
  });

  it("resets to default when switching to a wallet with no saved prefs (state-leak fix)", async () => {
    // Wallet A has custom prefs saved
    localStorage.setItem(storageKey(ADDR_A), JSON.stringify(["caesars"]));
    // Wallet B has no saved prefs (fresh wallet)

    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result, rerender } = renderHook(() => useBookPreferences());
    await waitFor(() => expect(result.current[0]).toEqual(["caesars"]));

    // Switch wallet — previously this leaked A's ["caesars"] into B's view
    mockUseAccount.mockReturnValue({ address: ADDR_B });
    rerender();
    await waitFor(() => expect(result.current[0]).toEqual([...ALL_BOOK_KEYS]));
  });

  it("loads each wallet's prefs independently on switch", async () => {
    localStorage.setItem(storageKey(ADDR_A), JSON.stringify(["draftkings"]));
    localStorage.setItem(storageKey(ADDR_B), JSON.stringify(["fanduel", "bet365"]));

    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result, rerender } = renderHook(() => useBookPreferences());
    await waitFor(() => expect(result.current[0]).toEqual(["draftkings"]));

    mockUseAccount.mockReturnValue({ address: ADDR_B });
    rerender();
    await waitFor(() => expect(result.current[0]).toEqual(["fanduel", "bet365"]));
  });

  it("clears corrupted localStorage entry and returns default", async () => {
    localStorage.setItem(storageKey(ADDR_A), "{not json");
    mockUseAccount.mockReturnValue({ address: ADDR_A });
    const { result } = renderHook(() => useBookPreferences());
    await waitFor(() => expect(result.current[0]).toEqual([...ALL_BOOK_KEYS]));
    expect(localStorage.getItem(storageKey(ADDR_A))).toBeNull();
  });
});
