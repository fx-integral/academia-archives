"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";

const TOS_ACCEPTED_KEY = "djinn_tos_accepted";
// Bump when ToS changes materially. The 2026-04-18 bump added Testnet
// disclaimer, Risk Disclosure + AUP + DMCA incorporation, force majeure,
// tax, electronic communications, and notice sections — users must re-accept.
const TOS_VERSION = "2026-04-18";

export function useTermsAccepted() {
  const [accepted, setAccepted] = useState<boolean | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(TOS_ACCEPTED_KEY);
    setAccepted(stored === TOS_VERSION);
  }, []);

  const accept = useCallback(() => {
    localStorage.setItem(TOS_ACCEPTED_KEY, TOS_VERSION);
    setAccepted(true);
  }, []);

  return { accepted, accept };
}

interface TermsModalProps {
  open: boolean;
  onAccept: () => void;
  onDecline: () => void;
}

export default function TermsModal({ open, onAccept, onDecline }: TermsModalProps) {
  const [scrolledToBottom, setScrolledToBottom] = useState(false);
  const [checked, setChecked] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
      );
      firstFocusable?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onDecline();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
        return;
      }
      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [open, onDecline]);

  if (!open) return null;

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (atBottom && !scrolledToBottom) {
      setScrolledToBottom(true);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tos-title"
        className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[85vh] flex flex-col"
      >
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-slate-100">
          <h2 id="tos-title" className="text-xl font-bold text-slate-900">
            Terms of Service
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            Please review and accept before continuing
          </p>
        </div>

        {/* Scrollable summary */}
        <div
          className="px-6 py-4 overflow-y-auto flex-1 text-sm text-slate-600 space-y-4"
          onScroll={handleScroll}
        >
          <p>
            By using Djinn, you acknowledge and agree to the following:
          </p>

          <div className="space-y-3">
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">1</span>
              <p>
                <strong>Information marketplace.</strong> Djinn is a platform for buying
                and selling analytical predictions. It is not a sportsbook, exchange, or
                gambling platform.
              </p>
            </div>
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">2</span>
              <p>
                <strong>Not financial advice.</strong> Signals are analytical predictions
                sold as information. Past performance does not guarantee future results.
              </p>
            </div>
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">3</span>
              <p>
                <strong>Smart contract risk.</strong> Funds deposited into smart contracts
                carry inherent risk. Transactions on the blockchain are irreversible.
              </p>
            </div>
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">4</span>
              <p>
                <strong>Prohibited conduct.</strong> You may not use Djinn for money
                laundering, sanctions evasion, insider trading, match-fixing, market
                manipulation, or any other illegal activity.
              </p>
            </div>
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">5</span>
              <p>
                <strong>Restricted regions.</strong> Djinn is not available in
                jurisdictions subject to U.S. sanctions (Cuba, Iran, North Korea, Syria,
                and others).
              </p>
            </div>
            <div className="flex gap-3">
              <span className="text-slate-400 font-mono text-xs mt-0.5">6</span>
              <p>
                <strong>Arbitration.</strong> Disputes are resolved through binding
                individual arbitration. You waive the right to participate in class
                actions. You may opt out within 30 days.
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <strong>Testnet:</strong> Djinn currently operates on Base Sepolia.
            USDC shown in the interface has no cash value. See the{" "}
            <Link
              href="/risk"
              target="_blank"
              className="underline font-medium"
            >
              Risk Disclosure
            </Link>{" "}
            for the full list of risks before depositing any funds.
          </div>

          <p className="text-slate-500">
            Read the full{" "}
            <Link
              href="/terms"
              target="_blank"
              className="text-slate-900 underline font-medium"
            >
              Terms of Service
            </Link>
            ,{" "}
            <Link
              href="/privacy"
              target="_blank"
              className="text-slate-900 underline font-medium"
            >
              Privacy Policy
            </Link>
            ,{" "}
            <Link
              href="/risk"
              target="_blank"
              className="text-slate-900 underline font-medium"
            >
              Risk Disclosure
            </Link>
            , and{" "}
            <Link
              href="/acceptable-use"
              target="_blank"
              className="text-slate-900 underline font-medium"
            >
              Acceptable Use Policy
            </Link>
            .
          </p>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-100 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-slate-600">
              I have read and agree to the{" "}
              <Link href="/terms" target="_blank" className="text-slate-900 underline">
                Terms of Service
              </Link>
              ,{" "}
              <Link href="/privacy" target="_blank" className="text-slate-900 underline">
                Privacy Policy
              </Link>
              ,{" "}
              <Link href="/risk" target="_blank" className="text-slate-900 underline">
                Risk Disclosure
              </Link>
              ,{" "}
              <Link href="/acceptable-use" target="_blank" className="text-slate-900 underline">
                Acceptable Use Policy
              </Link>
              , and{" "}
              <Link href="/dmca" target="_blank" className="text-slate-900 underline">
                DMCA Policy
              </Link>
              , and I am not located in a sanctioned jurisdiction.
            </span>
          </label>

          {!scrolledToBottom && (
            <p className="text-xs text-slate-500 italic">
              Please scroll through the summary above before accepting.
            </p>
          )}

          <div className="flex gap-3">
            <button
              onClick={onDecline}
              className="flex-1 rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
            >
              Decline
            </button>
            <button
              onClick={onAccept}
              disabled={!checked || !scrolledToBottom}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed transition-colors"
            >
              Accept &amp; Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
