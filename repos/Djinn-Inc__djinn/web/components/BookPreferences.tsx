"use client";

import { useState, useEffect } from "react";
import { useAccount } from "wagmi";

const ALL_BOOKS = [
  { key: "draftkings", label: "DraftKings" },
  { key: "fanduel", label: "FanDuel" },
  { key: "betmgm", label: "BetMGM" },
  { key: "caesars", label: "Caesars" },
  { key: "espnbet", label: "ESPN BET" },
  { key: "pointsbet", label: "PointsBet" },
  { key: "bet365", label: "bet365" },
  { key: "bovada", label: "Bovada" },
  { key: "betonlineag", label: "BetOnline" },
  { key: "mybookieag", label: "MyBookie" },
  { key: "williamhill_us", label: "William Hill" },
  { key: "unibet_us", label: "Unibet" },
  { key: "betrivers", label: "BetRivers" },
  { key: "wynnbet", label: "WynnBET" },
  { key: "superbook", label: "SuperBook" },
  { key: "fliff", label: "Fliff" },
  { key: "lowvig", label: "LowVig" },
  { key: "betus", label: "BetUS" },
];

/** Ordered list of all book keys. Exported so non-hook consumers (purchase
 * flow fallback) can share the same default without duplicating the list. */
export const ALL_BOOK_KEYS: readonly string[] = ALL_BOOKS.map((b) => b.key);

function getStorageKey(address: string): string {
  return `djinn:books:${address.toLowerCase()}`;
}

export function useBookPreferences(): [string[], (books: string[]) => void] {
  const { address } = useAccount();
  // Default new users (and pre-wallet-load) to ALL books selected. Prior
  // behavior started with [] which silently blocked every purchase because
  // the MPC check-odds call had no executable set to evaluate against.
  const [books, setBooks] = useState<string[]>(() => [...ALL_BOOK_KEYS]);

  useEffect(() => {
    if (!address) return;
    const saved = localStorage.getItem(getStorageKey(address));
    if (saved) {
      try {
        setBooks(JSON.parse(saved));
        return;
      } catch {
        // Corrupted entry — clear and fall through to default.
        localStorage.removeItem(getStorageKey(address));
      }
    }
    // No saved prefs for this address. Always reset to default-all so that
    // switching from wallet A (with custom prefs) to wallet B (no saved
    // prefs) doesn't leak A's selection into B's UI.
    setBooks([...ALL_BOOK_KEYS]);
  }, [address]);

  const updateBooks = (newBooks: string[]) => {
    setBooks(newBooks);
    if (address) {
      localStorage.setItem(getStorageKey(address), JSON.stringify(newBooks));
    }
  };

  return [books, updateBooks];
}

export default function BookPreferences() {
  const [books, updateBooks] = useBookPreferences();
  const [expanded, setExpanded] = useState(false);

  const toggleBook = (key: string) => {
    if (books.includes(key)) {
      updateBooks(books.filter((b) => b !== key));
    } else {
      updateBooks([...books, key]);
    }
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between text-left"
      >
        <div>
          <h3 className="text-sm font-medium text-slate-700">My Sportsbooks</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {books.length === 0
              ? `0/${ALL_BOOKS.length} selected — add some so purchases can execute`
              : `${books.length}/${ALL_BOOKS.length} selected`}
          </p>
        </div>
        <svg
          className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-2">
          {ALL_BOOKS.map((book) => (
            <label
              key={book.key}
              className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm cursor-pointer border transition-colors ${
                books.includes(book.key)
                  ? "border-blue-300 bg-blue-50 text-blue-700"
                  : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300"
              }`}
            >
              <input
                type="checkbox"
                checked={books.includes(book.key)}
                onChange={() => toggleBook(book.key)}
                className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              {book.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
