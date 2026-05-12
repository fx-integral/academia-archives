import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const rainbowState = {
  account: undefined as { displayName: string } | undefined,
  chain: undefined as { unsupported?: boolean } | undefined,
  mounted: true,
  openConnectModal: vi.fn(),
  openAccountModal: vi.fn(),
  openChainModal: vi.fn(),
};

function setRainbowState({
  account,
  chain,
}: {
  account?: { displayName: string };
  chain?: { unsupported?: boolean };
}) {
  rainbowState.account = account;
  rainbowState.chain = chain;
}

// Mock RainbowKit's ConnectButton.Custom
vi.mock("@rainbow-me/rainbowkit", () => ({
  ConnectButton: {
    Custom: ({ children }: { children: (props: Record<string, unknown>) => React.ReactNode }) =>
      children(rainbowState),
  },
}));

vi.mock("wagmi", () => ({
  useAccount: () => ({ address: undefined, isConnected: false }),
  useSwitchChain: () => ({ switchChainAsync: vi.fn() }),
}));

import WalletButton from "../WalletButton";

describe("WalletButton", () => {
  it("renders Connect Wallet button when not connected", () => {
    setRainbowState({});
    render(<WalletButton />);
    expect(screen.getByText("Connect Wallet")).toBeDefined();
    expect(screen.getByLabelText("Connect Wallet")).toBeDefined();
  });

  it("renders explicit target chain label on unsupported network", () => {
    setRainbowState({
      account: { displayName: "0x1234...abcd" },
      chain: { unsupported: true },
    });
    render(<WalletButton />);
    expect(screen.getByText("Switch to Base Sepolia")).toBeDefined();
  });
});
