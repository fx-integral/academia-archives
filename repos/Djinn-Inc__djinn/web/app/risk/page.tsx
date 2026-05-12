import Link from "next/link";

export const metadata = {
  title: "Risk Disclosure | Djinn",
  description:
    "Comprehensive risk disclosure for the Djinn Protocol: smart contract risk, validator/MPC risk, regulatory risk, and more.",
};

export default function Risk() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Risk Disclosure</h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <div className="not-prose my-8 rounded-xl border-2 border-amber-400 bg-amber-50 px-5 py-4">
        <p className="text-sm font-semibold text-amber-900 mb-1">
          Read this page before depositing any funds.
        </p>
        <p className="text-sm text-amber-900">
          Djinn is an experimental decentralized protocol. You can lose everything
          you deposit. This page describes the risks in plain English. If you do
          not understand a risk described here, do not use Djinn.
        </p>
      </div>

      <p>
        This Risk Disclosure is incorporated into the{" "}
        <Link href="/terms" className="text-slate-900 underline">
          Terms of Service
        </Link>
        . It supplements, but does not replace, the risks described there. By
        using Djinn, you acknowledge that you have read, understood, and accepted
        the risks below.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        1. Testnet Status
      </h2>
      <p>
        At the time this page was written, Djinn operates on <strong>Base Sepolia</strong>,
        a public test network. Tokens on Base Sepolia, including the USDC shown
        in the Djinn interface, have <strong>no cash value</strong>. They are for
        testing only. When Djinn migrates to Base mainnet, this page will be updated
        and deposits will involve real USDC with real economic value. Until then,
        do not treat testnet balances as representative of mainnet behavior, and
        do not send real funds to any testnet address.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        2. Smart Contract Risk
      </h2>
      <p>
        Djinn is a set of smart contracts on the Base blockchain. Smart contracts
        are software. Software has bugs. An undiscovered bug, a flawed upgrade, or
        a compromise of the governance keys could cause you to lose all funds you
        have deposited. The contracts are open source and have been reviewed
        internally and by third parties. That does not mean they are free of
        defects. No review finds every bug.
      </p>
      <p>
        The Djinn contracts are upgradeable. A privileged multisig operated by
        Djinn Inc., acting through a 72-hour on-chain timelock on mainnet, can
        deploy new implementations. An attacker who compromises the multisig, or
        Djinn Inc. itself acting in bad faith, could theoretically push a
        malicious upgrade. The timelock gives you time to exit, but only if you
        are watching the chain.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        3. Signal Quality Risk
      </h2>
      <p>
        Signals are analytical predictions. They can be wrong. The service-level
        agreement mechanism (SLA) provides partial structured compensation if a
        Genius&apos;s aggregated Quality Score is negative, but it does not
        guarantee accuracy. You can buy signals that turn out to be worthless,
        and in some scenarios (low-volume Geniuses, settlement delays, protocol
        bugs) you may receive less compensation than the SLA formula implies.
      </p>
      <p>
        Past performance shown on any Genius&apos;s track record does not predict
        future performance. A Genius with a long winning streak can start losing
        tomorrow. Track records on Djinn are verifiable on-chain, but verifiability
        is not the same as skill.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        4. Validator and MPC Risk
      </h2>
      <p>
        The Djinn Protocol depends on a decentralized network of validators on{" "}
        <strong>Bittensor Subnet 103</strong>. Validators hold Shamir shares of
        master seeds, perform secure multi-party computation (MPC) to derive
        signal keys on purchase, and vote on audit outcomes. If too many
        validators go offline simultaneously, signal purchases can fail, decryption
        can fail, and audits can stall. Settlement (collateral slashing or release)
        depends on a validator quorum reaching consensus on on-chain outcomes.
        Quorum failures, censorship by a colluding subset, or incentive misalignment
        can delay or prevent settlement.
      </p>
      <p>
        The MPC protocol itself is a newly deployed cryptographic system. A
        cryptographic flaw in the MPC implementation could, in principle, allow
        an attacker with enough compromised validators to reconstruct a seed and
        read signals, or to sign fraudulent settlements. Current bootstrap
        parameters (Shamir t-of-n) are documented in the whitepaper and are
        designed to tolerate a minority of bad validators; they do not tolerate
        majority collusion.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        5. Bittensor Network Risk
      </h2>
      <p>
        Djinn validators and miners are registered on Bittensor Subnet 103 and
        are rewarded in TAO, the Bittensor native token. The economic security
        of the validator set depends on TAO having and retaining value, on the
        Bittensor governance process not materially changing subnet parameters
        in a way that breaks Djinn, and on the subnet continuing to be registered
        in good standing. A deregistration event, a hostile governance proposal,
        or a severe TAO price collapse could weaken validator incentives to the
        point that settlement is unreliable. TAO holders are subject to their own
        regulatory, custody, and market risks, independent of Djinn.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        6. Blockchain Risk
      </h2>
      <p>
        Transactions on the Base blockchain are irreversible. If you send funds
        to the wrong address, or sign a malicious transaction prompted by a
        phishing site impersonating Djinn, those funds are unrecoverable. Network
        congestion can cause transaction fees to spike. A Base outage, a sequencer
        failure, or a reorg deeper than the finality threshold could delay,
        re-order, or, in edge cases, invalidate transactions you believed were
        confirmed. Base is operated by Coinbase and has its own disclosures and
        risks; consult Coinbase&apos;s materials for details on Base&apos;s
        architecture and governance.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        7. Stablecoin Risk
      </h2>
      <p>
        The stablecoin used for settlement is <strong>USDC</strong>, issued by
        Circle. USDC is a private stablecoin; it is not a bank deposit, is not
        FDIC-insured, and is not a claim on the United States government. Its
        one-to-one peg with the U.S. dollar depends on Circle&apos;s ability to
        honor redemptions. A loss of the peg (de-pegging), a regulatory action
        against Circle, or an operational failure at Circle could cause USDC to
        trade below par, which would reduce the real value of your Djinn balance.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        8. Regulatory Risk
      </h2>
      <p>
        The legal status of information marketplaces, cryptocurrencies, smart
        contracts, decentralized finance, and related technologies varies by
        jurisdiction and is evolving rapidly. Regulators may, at any time,
        characterize parts of Djinn as a regulated activity (for example, as
        gambling, money transmission, a securities offering, or commodity
        trading), whether or not we consider that characterization correct.
        Regulatory action could force Djinn to restrict service in your
        jurisdiction, shut down user-facing websites, freeze features, or comply
        with information requests about users within the reach of applicable law.
      </p>
      <p>
        Your use of Djinn may itself be illegal in your jurisdiction. You are
        solely responsible for compliance with all laws applicable to you,
        including gambling prohibitions, tax reporting, and sanctions law. Djinn
        does not offer legal advice and is not a substitute for consulting your
        own counsel.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        9. Custody and Private Key Risk
      </h2>
      <p>
        Djinn is non-custodial. Your wallet private key, and if you use a smart
        wallet your recovery method, are solely under your control. If you lose
        your key, your seed phrase, or access to your wallet provider, no one
        at Djinn can restore your funds. If your key is stolen (through a phishing
        attack, device compromise, malicious browser extension, or other means),
        the thief can take everything you have deposited. We will never ask for
        your private key, seed phrase, or password for any reason.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        10. Front-End and Infrastructure Risk
      </h2>
      <p>
        The djinn.gg website is one front-end to the protocol. If the front-end
        is compromised (DNS hijack, TLS compromise, supply-chain attack on our
        hosting or dependencies), you could be served malicious code that prompts
        you to sign transactions that drain your funds. To mitigate this, advanced
        users can interact directly with the smart contracts from a wallet of
        their choice, or from an independent front-end. The contracts are
        permissionless; the website is not the protocol.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        11. Counterparty Risk (Geniuses and Idiots)
      </h2>
      <p>
        Djinn reduces, but does not eliminate, counterparty risk. Collateral locks
        create structural protection for Idiots if Geniuses underperform, and
        Idiot balances are held in contracts, not by Geniuses. But slashing is
        capped at posted collateral. A Genius who is catastrophically wrong on a
        long series of signals will only refund up to the collateral they posted;
        further losses attributed to their signals are not covered. Likewise, an
        Idiot who defaults on platform fees can only be pursued to the extent of
        their on-platform balance.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        12. Market Manipulation and Insider Risk
      </h2>
      <p>
        Djinn cannot prevent all forms of manipulation or insider abuse. A
        sophisticated actor could attempt to wash-trade their own signals to
        inflate a track record, collude with other participants to steer audits,
        or exploit information asymmetries (advance injury reports, line-movement
        arbitrage, inside access to officiating or lineups) in ways that
        disadvantage other users. Our{" "}
        <Link href="/acceptable-use" className="text-slate-900 underline">
          Acceptable Use Policy
        </Link>{" "}
        prohibits these behaviors, but prohibition is not the same as prevention.
        Bear this risk in mind when evaluating any track record.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        13. Operational Risk
      </h2>
      <p>
        Djinn is operated by a small team. The team can make mistakes.
        Configuration errors, botched deployments, stuck cron jobs, validators
        running stale versions, or an outage of a third-party service (odds
        provider, RPC provider, hosting) can cause transient or persistent
        degradation of service. In rare cases, operational mistakes could affect
        settlement or pricing. Monitoring and incident response are in place but
        are not infallible.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14. Credit and Recovery Risk
      </h2>
      <p>
        Djinn Credits are non-transferable, non-cashable platform credits that
        function only as a discount on future signal purchases. They are not a
        debt instrument and are not redeemable for cash. A protocol change,
        contract upgrade, or discontinuation of the service could render credits
        unusable. Treat them as store credit with all that implies.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        15. Loss of Service
      </h2>
      <p>
        Djinn may cease to operate. The team may dissolve, the company may enter
        bankruptcy, a regulator may compel takedown of the website, or the
        Bittensor subnet may be deregistered. In any of these events, the smart
        contracts remain on-chain and, to the extent your funds are in them and
        withdrawal functions remain callable, you can withdraw. But a fully
        operational ongoing service is not guaranteed, and the user-interface
        path to withdrawal may be unavailable.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        16. No Financial Advice
      </h2>
      <p>
        Nothing published by Djinn, its officers, employees, contractors, or
        community members is financial advice, investment advice, legal advice,
        tax advice, or a recommendation to wager on any outcome. Any decisions
        you make based on information obtained through Djinn are your own.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        17. No Warranty
      </h2>
      <p>
        Djinn is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo;
        without any warranty, express or implied. Nothing on this page, in the
        whitepaper, on the website, or in any other Djinn material constitutes a
        warranty of functionality, uptime, accuracy, fitness for purpose,
        merchantability, non-infringement, or freedom from defect.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        18. Acknowledgment
      </h2>
      <p>
        By connecting a wallet to Djinn, interacting with the API, or depositing
        funds, you acknowledge that you have read this Risk Disclosure in full,
        that you understand each risk described, and that you accept full
        responsibility for your own conduct and for any loss that may arise from
        your use of the protocol.
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
