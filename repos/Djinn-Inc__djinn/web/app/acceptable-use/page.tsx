import Link from "next/link";

export const metadata = {
  title: "Acceptable Use Policy | Djinn",
  description:
    "Djinn Acceptable Use Policy: what is and isn't permitted on the protocol, and how violations are handled.",
};

export default function AcceptableUse() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">
        Acceptable Use Policy
      </h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <p>
        This Acceptable Use Policy (&ldquo;AUP&rdquo;) describes the conduct that
        is permitted and prohibited on the Djinn Protocol. It supplements, and is
        incorporated by reference into, the{" "}
        <Link href="/terms" className="text-slate-900 underline">
          Terms of Service
        </Link>
        . Violation of this AUP is a violation of the Terms.
      </p>

      <p>
        Djinn is a decentralized protocol. Some of the rules below are enforced
        by smart contracts, some by the validator network, and some by the front
        end at djinn.gg. Enforcement tools available to Djinn Inc. at the
        front-end level do not extend to the on-chain contracts, which are
        permissionless by design. This does not make prohibited conduct allowed;
        it means that prohibited conduct is subject to law, community norms,
        and the enforcement mechanisms available to affected parties.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        1. Permitted Conduct
      </h2>
      <p>On Djinn, you may:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          Create signals reflecting your own genuine analysis of public or
          legally obtained information (public odds, public injury reports,
          public statistics, proprietary models, personal research)
        </li>
        <li>
          Purchase signals that other Geniuses have published
        </li>
        <li>
          Deposit and withdraw USDC collateral and platform balance through the
          protocol&apos;s documented smart contract functions
        </li>
        <li>
          Publish your track record, write about your methodology, and promote
          your Genius profile, provided you do not misrepresent your performance
          or methodology
        </li>
        <li>
          Run validators or miners on Bittensor Subnet 103 in good faith and in
          compliance with the subnet&apos;s technical and governance rules
        </li>
        <li>
          Build third-party applications on top of the public Djinn API or the
          public contract interfaces, subject to the Terms and this AUP
        </li>
        <li>
          Report security vulnerabilities responsibly (see Section 7 below)
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        2. Prohibited Conduct: Integrity
      </h2>
      <p>
        You may not use Djinn, directly or indirectly, to engage in conduct that
        corrupts the integrity of the information marketplace. Without limitation,
        you may not:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Wash-trade.</strong> You may not purchase your own signals,
          coordinate with another party to purchase your signals, or structure
          transactions with a primary purpose of inflating your track record,
          Quality Score, or visibility on the leaderboard.
        </li>
        <li>
          <strong>Sybil and coordination.</strong> You may not operate multiple
          wallets, accounts, or identities to circumvent rate limits, evade
          enforcement, inflate your own track record, or manipulate audit
          outcomes. You may not coordinate with other users to manipulate Quality
          Scores or audit results.
        </li>
        <li>
          <strong>Audit manipulation.</strong> You may not submit false outcomes
          to the outcome-voting process, bribe validators, or otherwise interfere
          with the settlement of audits.
        </li>
        <li>
          <strong>Fake signal creation.</strong> You may not publish signals
          known to be baseless, random, or chosen to extract fees without
          intending genuine analytical content. This includes &ldquo;signal
          farming&rdquo; patterns designed to game the Quality Score formula
          rather than offer real analysis.
        </li>
        <li>
          <strong>Impersonation.</strong> You may not impersonate another Genius,
          analyst, team, athlete, sportsbook, or Djinn team member.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        3. Prohibited Conduct: Information Misuse
      </h2>
      <p className="italic text-slate-500">
        The following prohibitions apply to the creation and sale of information
        on Djinn&apos;s information marketplace. They do not describe anyone&apos;s
        downstream use of that information. Djinn is not a sportsbook and does
        not facilitate, intermediate, or process bets; these rules exist because
        monetizing stolen or privileged information is fraud regardless of
        whether the buyer ever places a wager.
      </p>
      <p>
        You may not create or sell signals based on material non-public
        information (MNPI). This includes, without limitation, information
        obtained through privileged access to:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Teams, coaches, or team personnel</li>
        <li>Players, agents, or families of players</li>
        <li>Officiating bodies, referees, or umpires</li>
        <li>Leagues, conferences, or governing bodies</li>
        <li>Sportsbooks, odds-compiling firms, or liquidity providers</li>
        <li>
          Medical staff, team doctors, training staff, or anyone with
          pre-public injury or fitness information
        </li>
        <li>
          Government or law-enforcement sources that would not legally disclose
          the information to the public
        </li>
      </ul>
      <p>
        You also may not attempt to obtain MNPI from these sources, pay for
        MNPI, or solicit MNPI from parties who may be under fiduciary or
        contractual duties not to disclose it.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        4. Prohibited Conduct: Match-Fixing and Event Manipulation
      </h2>
      <p>
        You may not use Djinn in connection with any scheme to influence the
        outcome, pace, score, or material aspects of any sporting event. This
        includes but is not limited to:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Point-shaving, tanking, or spot-fixing</li>
        <li>
          Bribing or paying athletes, coaches, officials, or team staff to
          influence an event
        </li>
        <li>
          Working with a participant in an event to change its outcome or any
          component of its outcome
        </li>
        <li>
          Using information about a pending fix to create or price signals
        </li>
      </ul>
      <p>
        Match-fixing is a criminal offense in most jurisdictions. Djinn will
        cooperate with any legitimate criminal investigation into match-fixing
        identified through on-chain activity connected to the protocol, to the
        extent permitted by applicable law.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        5. Prohibited Conduct: Financial Crime
      </h2>
      <p>You may not use Djinn to:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Launder money.</strong> Including structuring transactions to
          obscure the source, ownership, or destination of funds; layering
          deposits and withdrawals to disguise origin; or integrating
          proceeds of crime into the protocol balance.
        </li>
        <li>
          <strong>Finance terrorism.</strong> Including providing material
          support to any person or entity designated as a terrorist or
          terrorist organization by any competent authority.
        </li>
        <li>
          <strong>Evade sanctions.</strong> Including facilitating transactions
          involving persons, entities, or jurisdictions subject to comprehensive
          sanctions under U.S., U.N., E.U., or U.K. law, or acting on behalf of
          such persons or entities.
        </li>
        <li>
          <strong>Commit fraud.</strong> Including deceiving other users about
          your identity, qualifications, track record, methodology, or the
          nature of a signal.
        </li>
        <li>
          <strong>Engage in unlicensed regulated activity.</strong> Including
          operating a sportsbook, money services business, or securities
          brokerage out of Djinn without the authorizations your jurisdiction
          requires.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        6. Prohibited Conduct: Protocol and Infrastructure
      </h2>
      <p>You may not:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          Interfere with the operation of the smart contracts, the validator
          network, the miner network, or the djinn.gg front end, beyond the
          intended public interfaces
        </li>
        <li>
          Run automated systems that intentionally degrade service for other
          users, including denial-of-service floods, spammy signal creation to
          consume validator capacity, or scraping at a rate that burdens our
          infrastructure
        </li>
        <li>
          Reverse-engineer, decompile, or disassemble any component of the
          protocol for the purpose of exploiting it
        </li>
        <li>
          Attempt to extract master seeds, Shamir shares, or any other secret
          material from validators, miners, or other users through technical,
          social, or legal means
        </li>
        <li>
          Use the Djinn name, logo, or branding to suggest an endorsement,
          partnership, or affiliation that does not exist
        </li>
        <li>
          Circumvent any geo-block, rate limit, or access control, including by
          using VPNs, proxies, or Tor to obscure your jurisdiction in order to
          access the service from a restricted location
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        7. Responsible Security Disclosure
      </h2>
      <p>
        Responsible security research is permitted and encouraged. If you
        discover a vulnerability:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          Report it privately to{" "}
          <a
            href="mailto:security@djinn.gg"
            className="text-slate-900 underline"
          >
            security@djinn.gg
          </a>{" "}
          before any public disclosure
        </li>
        <li>
          Do not exploit the vulnerability beyond the minimum needed to
          demonstrate it
        </li>
        <li>
          Do not withdraw funds that are not yours, and do not access data that
          is not yours
        </li>
        <li>
          Give us a reasonable opportunity to investigate and remediate before
          publishing
        </li>
      </ul>
      <p>
        Djinn will not pursue legal action for good-faith security research
        conducted in accordance with these principles. A formal bug-bounty
        program, with scope and payout tables, will be published before mainnet
        launch.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        8. Content You Submit
      </h2>
      <p>
        Some features of Djinn (support messages, feedback, API requests) let
        you submit free-text content. You are solely responsible for what you
        submit. You may not submit content that:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Is illegal, defamatory, threatening, harassing, or fraudulent</li>
        <li>Infringes another party&apos;s intellectual property rights</li>
        <li>Contains malware or exploit payloads</li>
        <li>
          Contains personal data of other individuals that you have no lawful
          basis to share
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        9. Enforcement
      </h2>
      <p>
        Enforcement of this AUP is tiered, reflecting the decentralized nature
        of the protocol:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Front-end restrictions.</strong> Djinn Inc. can restrict
          access to djinn.gg, the hosted API, and hosted support features for
          wallet addresses or network sources engaged in prohibited conduct.
        </li>
        <li>
          <strong>Reputation and leaderboard.</strong> Signals, Geniuses, or
          patterns associated with prohibited conduct can be removed from the
          hosted leaderboard and search. The underlying on-chain data is
          immutable and will remain visible to any third party that indexes it.
        </li>
        <li>
          <strong>Cooperation with authorities.</strong> Djinn Inc. will
          cooperate with valid legal process (subpoena, court order, or
          equivalent) to the extent required by applicable law.
        </li>
        <li>
          <strong>Smart contract remediation.</strong> If a protocol upgrade can
          safely address an abuse pattern without harming innocent users, Djinn
          governance may consider such an upgrade. Upgrades follow the timelock
          process described in the Terms.
        </li>
      </ul>
      <p>
        Djinn Inc. will generally not comment on individual enforcement actions.
        Enforcement is best-effort and is not a guarantee that no prohibited
        conduct will ever occur on the protocol.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        10. Reporting Violations
      </h2>
      <p>
        If you believe another user is violating this AUP, please report it to{" "}
        <a href="mailto:abuse@djinn.gg" className="text-slate-900 underline">
          abuse@djinn.gg
        </a>
        . Include the wallet address, signal ID, transaction hash, or other
        identifying details you can provide, along with a description of the
        conduct. Please do not make public accusations without giving us a
        reasonable chance to investigate.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        11. Changes
      </h2>
      <p>
        We may update this AUP from time to time. Material changes will be
        posted here with an updated date. Continued use of Djinn after changes
        constitutes acceptance of the revised AUP.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        12. Contact
      </h2>
      <p>
        For AUP questions, reach us at{" "}
        <a
          href="mailto:legal@djinn.gg"
          className="text-slate-900 underline"
        >
          legal@djinn.gg
        </a>
        .
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
