import { ADDRESSES } from "@/lib/contracts";

export type GeniusOnboardingCta = {
  label: string;
  href: string;
  external?: boolean;
};

export type GeniusOnboardingStep = {
  step: string;
  label: string;
  hint: string;
  active?: boolean;
  ctas?: GeniusOnboardingCta[];
};

export function getGeniusOnboardingSteps(
  usdcAddress = ADDRESSES.usdc,
): GeniusOnboardingStep[] {
  return [
    {
      step: "1",
      label: "Connect your wallet",
      hint: "Click \"Connect Wallet\" in the top right. We recommend Coinbase Smart Wallet: free to create, no gas fees, works with just an email.",
      active: true,
    },
    {
      step: "2",
      label: "Switch to Base network",
      hint: "In your wallet network menu, choose Base Sepolia (chain ID 84532).",
      ctas: [
        { label: "Add Base Sepolia", href: "https://chainlist.org/chain/84532", external: true },
      ],
    },
    {
      step: "3",
      label: "Get test USDC",
      hint: `After connecting on Base Sepolia, use the top banner's "Get free test USDC" button to mint Djinn MockUSDC directly to your wallet. Token: ${usdcAddress}. If gas is empty, use the ETH faucet first. Start small ($10-$50 equivalent) while learning.`,
      ctas: [
        { label: "Open ETH faucet", href: "https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet", external: true },
        { label: "Need help? Ask Discord", href: "https://discord.com/channels/799672011265015819/1465362098971345010", external: true },
      ],
    },
    {
      step: "4",
      label: "Deposit USDC collateral",
      hint: "After connecting, use the Deposit panel on this page. Collateral is refundable, locked only while picks are active, and slashable only up to your locked amount.",
      ctas: [
        { label: "Read collateral rules", href: "/docs/how-it-works" },
      ],
    },
    {
      step: "5",
      label: "Create your first signal",
      hint: "A signal is an encrypted sports pick (market, side, price, expiry). Buyers see metadata and your record before purchase.",
      ctas: [
        { label: "Open signal builder", href: "/genius/signal/new" },
      ],
    },
  ];
}
