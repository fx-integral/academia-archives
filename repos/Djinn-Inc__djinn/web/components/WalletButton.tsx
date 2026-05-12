"use client";

import { useState } from "react";
import { useAccount, useSwitchChain } from "wagmi";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import TermsModal, { useTermsAccepted } from "./TermsModal";

const IS_E2E = process.env.NEXT_PUBLIC_E2E_TEST === "true";
const TARGET_CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? "84532");
const TARGET_CHAIN_NAME = TARGET_CHAIN_ID === 8453 ? "Base" : "Base Sepolia";

function E2EWalletButton() {
  const { address, isConnected } = useAccount();
  if (!isConnected) return null;
  return (
    <span
      data-testid="wallet-address"
      className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700"
    >
      {address?.slice(0, 6)}...{address?.slice(-4)}
    </span>
  );
}

export default function WalletButton() {
  if (IS_E2E) return <E2EWalletButton />;
  return <WalletButtonInner />;
}

function WalletButtonInner() {
  const { accepted, accept } = useTermsAccepted();
  const { switchChainAsync } = useSwitchChain();
  const [showTerms, setShowTerms] = useState(false);
  // Store the openConnectModal callback so we can call it after ToS acceptance
  const [pendingConnect, setPendingConnect] = useState<(() => void) | null>(null);

  function handleConnectClick(openConnectModal: () => void) {
    if (accepted) {
      openConnectModal();
    } else {
      setPendingConnect(() => openConnectModal);
      setShowTerms(true);
    }
  }

  function handleAccept() {
    accept();
    setShowTerms(false);
    if (!pendingConnect) return;
    // Open the wallet connect modal after accepting
    pendingConnect();
    setPendingConnect(null);
  }

  function handleDecline() {
    setShowTerms(false);
    setPendingConnect(null);
  }

  async function handleWrongNetworkClick(openChainModal: () => void) {
    const switchPromise = switchChainAsync?.({ chainId: TARGET_CHAIN_ID });
    if (!switchPromise) {
      openChainModal();
      return;
    }

    try {
      await switchPromise;
    } catch {
      openChainModal();
    }
  }

  return (
    <>
      <TermsModal
        open={showTerms}
        onAccept={handleAccept}
        onDecline={handleDecline}
      />
      <ConnectButton.Custom>
        {({
          account,
          chain,
          openConnectModal,
          openAccountModal,
          openChainModal,
          mounted,
        }) => {
          const ready = mounted;
          const connected = ready && account && chain;

          if (!ready) return null;

          if (!connected) {
            return (
              <button
                onClick={() => handleConnectClick(openConnectModal)}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 transition-colors"
                aria-label="Connect Wallet"
              >
                <svg
                  aria-hidden="true"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 12V7H5a2 2 0 0 1 0-4h14v4" />
                  <path d="M3 5v14a2 2 0 0 0 2 2h16v-5" />
                  <path d="M18 12a2 2 0 0 0 0 4h4v-4Z" />
                </svg>
                Connect Wallet
              </button>
            );
          }

          if (chain?.unsupported) {
            return (
              <button
                onClick={() => void handleWrongNetworkClick(openChainModal)}
                className="rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white"
              >
                Switch to {TARGET_CHAIN_NAME}
              </button>
            );
          }

          return (
            <button
              onClick={openAccountModal}
              data-testid="wallet-address"
              className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors"
            >
              {account.displayName}
            </button>
          );
        }}
      </ConnectButton.Custom>
    </>
  );
}
