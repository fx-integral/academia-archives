import Link from "next/link";

export const metadata = {
  title: "Support | Djinn",
  description:
    "How to reach the Djinn team, what to try when something goes wrong, and self-service recovery paths.",
};

export default function Support() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Support</h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <p>
        Djinn is a decentralized protocol, not a custodial platform. Most
        user-facing problems have a self-service recovery path that does not
        require contacting anyone. This page documents those paths first, then
        the ways to reach a human operator when they are exhausted.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        Before contacting us
      </h2>
      <p>
        Try the self-service steps below. They fix the majority of cases
        without a round-trip:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Page stuck loading / wallet won&rsquo;t connect:</strong>{" "}
          disconnect the wallet, hard-refresh (Ctrl/Cmd-Shift-R), clear the
          site&rsquo;s local storage, and reconnect. Most &ldquo;stuck&rdquo;
          UI states are stale local cache, not protocol state.
        </li>
        <li>
          <strong>Transaction submitted but signal never appeared:</strong>{" "}
          check the transaction hash on{" "}
          <a
            href="https://sepolia.basescan.org"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-900 underline"
          >
            basescan
          </a>
          . If the tx reverted, the error is the source of truth. If it
          succeeded but the UI disagrees, reload the page; the indexer usually
          catches up within a few blocks.
        </li>
        <li>
          <strong>Lost wallet / lost seed phrase:</strong> Djinn cannot
          recover your wallet. Your funds are controlled by the keys on your
          device. Contact your wallet provider (Coinbase, MetaMask, etc.) for
          device-level recovery options.
        </li>
        <li>
          <strong>Signal purchased but decryption failed:</strong> the
          protocol includes a key-recovery path that reconstructs the
          decryption key from validator shares. This is triggered
          automatically on purchase. If it failed, the on-chain{" "}
          <code>KeyRecovery</code> contract will have an event indicating why.
          Re-trying the purchase from a fresh wallet session typically resolves
          transient failures.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        Funds stuck in escrow
      </h2>
      <p>
        Every purchase goes through the on-chain <code>Escrow</code> contract.
        Funds are released automatically when the audit completes. If an audit
        is slow or stalled, a few things are worth checking before treating
        the funds as stuck:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          Audits are queue-based. Under normal load most audits settle within
          a few hours of the event&rsquo;s outcome being publicly known. During
          high-traffic windows (championship nights, World Cup matchdays) the
          queue can extend. See{" "}
          <Link href="/network" className="text-slate-900 underline">
            the network page
          </Link>{" "}
          for current queue depth.
        </li>
        <li>
          If the audit is blocked waiting for validator quorum (shown as
          &ldquo;waiting for votes&rdquo;), it will resume automatically when
          quorum is reached. No action is required from you.
        </li>
        <li>
          If you see an audit in the &ldquo;settled&rdquo; state but your
          escrow balance didn&rsquo;t change, hard-refresh the page. The UI
          is a read of on-chain state; the on-chain state is the ground truth.
        </li>
        <li>
          Time-limited escape hatch: the <code>Escrow</code> contract
          includes an owner-callable <code>forceSettle</code> path that can
          unblock a genuinely stuck audit after a timeout. Operator
          engagement is required to invoke it. Contact us via the channels
          below if you believe your case qualifies.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        Contact
      </h2>
      <p>
        Djinn is a small team. We read every message but respond on a
        best-effort basis. There is no paid support tier and no guaranteed
        response time. For anything time-sensitive (locked funds, suspected
        exploit), prefer the channels at the top of the list.
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Suspected security issue (private disclosure):</strong>{" "}
          <a
            href="mailto:security@djinn.gg"
            className="text-slate-900 underline"
          >
            security@djinn.gg
          </a>
          . Please do not post exploit details in public channels; we will
          respond and coordinate disclosure.
        </li>
        <li>
          <strong>Funds-stuck or settlement question:</strong>{" "}
          <a
            href="mailto:support@djinn.gg"
            className="text-slate-900 underline"
          >
            support@djinn.gg
          </a>
          . Please include the transaction hash, wallet address, and the URL
          you were on when the issue appeared.
        </li>
        <li>
          <strong>General questions / community:</strong> our{" "}
          <a
            href="https://discord.com/channels/799672011265015819/1465362098971345010"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-900 underline"
          >
            Discord channel
          </a>{" "}
          or{" "}
          <a
            href="https://x.com/djinn_gg"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-900 underline"
          >
            @djinn_gg on X
          </a>
          .
        </li>
        <li>
          <strong>Bug reports and feature requests:</strong> the in-app
          feedback button (bottom of every page) or{" "}
          <a
            href="https://github.com/Djinn-Inc/djinn/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-900 underline"
          >
            GitHub issues
          </a>
          .
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        What we cannot do
      </h2>
      <p>
        Because Djinn is decentralized and non-custodial:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>We cannot reverse a transaction.</li>
        <li>We cannot unlock a wallet you&rsquo;ve lost access to.</li>
        <li>
          We cannot override the outcome of a settled audit. Audits are
          resolved by an on-chain vote among validator signers; we do not
          hold a majority vote and cannot unilaterally change a result.
        </li>
        <li>
          We cannot see the contents of your signal. All signal content is
          encrypted client-side; the protocol is designed so the operator
          never has the plaintext.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        Network status
      </h2>
      <p>
        Real-time validator and miner status is public on{" "}
        <Link href="/network" className="text-slate-900 underline">
          the network page
        </Link>
        . If something widespread is broken, it will be visible there first.
      </p>

      <div className="mt-12 pt-8 border-t border-slate-200">
        <Link
          href="/"
          className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
        >
          &larr; Back to Djinn
        </Link>
      </div>
    </div>
  );
}
