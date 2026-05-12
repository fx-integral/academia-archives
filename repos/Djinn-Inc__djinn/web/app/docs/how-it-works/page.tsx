import Link from "next/link";
import Tooltip from "@/components/Tooltip";

export const metadata = {
  title: "How Djinn Works | Docs",
  description: "The Djinn protocol in 5 minutes: signals, MPC, settlement, and track records.",
};

function Step({ number, title, color, children }: {
  number: string;
  title: string;
  color: "genius" | "idiot" | "slate";
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-5">
      <div
        className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold ${
          color === "genius"
            ? "bg-genius-100 text-genius-700"
            : color === "idiot"
              ? "bg-idiot-100 text-idiot-700"
              : "bg-slate-100 text-slate-600"
        }`}
      >
        {number}
      </div>
      <div className="pt-1">
        <h3 className="font-semibold text-slate-900 mb-1">{title}</h3>
        <p className="text-sm text-slate-600 leading-relaxed">{children}</p>
      </div>
    </div>
  );
}

export default function HowItWorks() {
  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-10">
        <Link href="/docs" className="text-sm text-slate-500 hover:text-slate-700 transition-colors">
          &larr; Back to Docs
        </Link>
      </div>

      <h1 className="text-3xl font-bold text-slate-900 mb-3">How Djinn Works</h1>
      <p className="text-lg text-slate-500 mb-12">
        From prediction to settlement in 6 steps. The entire flow is encrypted,
        decentralized, and settled in <Tooltip term="USDC" />.
      </p>

      <div className="space-y-8">
        <Step number="1" title="Genius creates a signal" color="genius">
          A Genius has an analytical prediction (e.g., &ldquo;Celtics -4.5&rdquo;). They
          encrypt it locally in their browser using <Tooltip term="AES-256-GCM" /> and
          hide it among a configurable set of <Tooltip term="decoy lines" /> drawn from
          the same sport, time window, and price range. The encrypted blob is committed
          on-chain. The real pick&apos;s index is split across validators
          using <Tooltip term="Shamir's Secret Sharing" />. Nobody, not even Djinn, can
          see which line is real.
        </Step>

        <Step number="2" title="Idiot browses and purchases" color="idiot">
          An Idiot browses available signals by sport, checks the Genius&apos;s track
          record, and decides to buy. They deposit <Tooltip term="USDC" /> into the
          Escrow contract. Validators independently query the miner network to confirm
          the buyer&apos;s preferred sportsbooks still offer prices at-or-above the
          Genius&apos;s committed limit, then run an <Tooltip term="MPC" /> availability
          check that verifies the real pick is among the executable lines without
          revealing which one. If available, the Idiot receives key shares from a
          threshold of validators and decrypts the signal locally in the browser.
        </Step>

        <Step number="3" title="The game happens" color="slate">
          The sporting event plays out. Validators independently query official sports
          data sources to determine final scores. They resolve every line (real and
          decoys) against the game result, producing one outcome per line. No single
          validator knows which outcome corresponds to the real pick. The selection
          happens later, during batch settlement.
        </Step>

        <Step number="4" title="MPC batch settlement" color="slate">
          Once enough signals between a Genius-Idiot pair have resolved outcomes,
          validators run a secure <Tooltip term="MPC">multi-party computation</Tooltip> that
          computes a per-line gain vector and selects the value at the secret real index
          via Shamir reconstruction. The output is a single signed attestation: the
          aggregate <Tooltip term="Quality Score" /> for the batch, plus any damages owed.
          The intermediate computation reveals nothing about which line was real. When a
          Shamir threshold of validators agree, settlement is finalized on-chain.
        </Step>

        <Step number="5" title="USDC moves" color="slate">
          If the <Tooltip term="Quality Score" /> is positive (the Genius performed well), they
          keep the fees. If negative (poor performance), the Genius&apos;s collateral is slashed:
          the Idiot gets a <Tooltip term="USDC" /> refund and Djinn Credits for any excess
          damages. The Genius can claim their earned fees after a 48-hour dispute window.
        </Step>

        <Step number="6" title="Track record builds" color="slate">
          Every settlement is recorded on-chain on <Tooltip term="Base" />. A Genius&apos;s track
          record is the complete, immutable history of their Quality Scores. No one can fake it,
          inflate it, or hide bad results. Buyers can verify any Genius&apos;s full history by
          reading the blockchain directly.
        </Step>
      </div>

      {/* Key properties */}
      <div className="mt-14 pt-8 border-t border-slate-200">
        <h2 className="text-xl font-semibold text-slate-900 mb-6">Key properties</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <div>
            <h3 className="font-semibold text-slate-900 mb-1">Signal secrecy</h3>
            <p className="text-sm text-slate-600">
              Predictions are encrypted client-side with <Tooltip term="AES-256-GCM" />.
              The real pick is hidden among a configurable set
              of <Tooltip term="decoy lines" /> drawn from the same sport and price range.
              The index is <Tooltip term="Shamir's Secret Sharing">Shamir-split</Tooltip> across
              validators and reconstructed only inside <Tooltip term="MPC" /> at settlement.
              No single party ever sees the plaintext pick.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 mb-1">Verifiable track records</h3>
            <p className="text-sm text-slate-600">
              Every settlement is on-chain. <Tooltip term="Quality Score">Quality Scores</Tooltip> are
              computed by <Tooltip term="MPC">multi-party computation</Tooltip> and signed
              by a Shamir threshold of independent validators. Track records are
              immutable and publicly auditable.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 mb-1">Non-custodial</h3>
            <p className="text-sm text-slate-600">
              All funds are held in auditable smart contracts
              on <Tooltip term="Base" />, never by Djinn. Deposits, withdrawals, and settlements
              are executed by code, not people.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 mb-1">Decentralized infrastructure</h3>
            <p className="text-sm text-slate-600">
              Validators and miners run on <Tooltip term="Bittensor" /> (Subnet 103). Settlement
              consensus requires 2/3+ independent validators. No single point of failure or trust.
            </p>
          </div>
        </div>
      </div>

      {/* CTAs */}
      <div className="mt-12 flex flex-wrap gap-4">
        <Link
          href="/genius"
          className="rounded-lg border-2 border-genius-200 px-5 py-2.5 text-sm font-semibold text-genius-700 hover:bg-genius-50 transition-colors"
        >
          Start as a Genius
        </Link>
        <Link
          href="/idiot"
          className="rounded-lg border-2 border-idiot-200 px-5 py-2.5 text-sm font-semibold text-idiot-700 hover:bg-idiot-50 transition-colors"
        >
          Start as an Idiot
        </Link>
        <Link
          href="/docs/api"
          className="rounded-lg border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
        >
          API Reference
        </Link>
      </div>

      <div className="mt-8 pb-4">
        <Link href="/docs" className="text-sm text-slate-500 hover:text-slate-700 transition-colors">
          &larr; Back to Docs
        </Link>
      </div>
    </div>
  );
}
