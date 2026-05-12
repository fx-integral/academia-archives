import Link from "next/link";

export const metadata = {
  title: "Terms of Service | Djinn",
};

export default function Terms() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Terms of Service</h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <p>
        These Terms of Service (&ldquo;Terms&rdquo;) govern your use of the Djinn
        Protocol (&ldquo;Djinn,&rdquo; &ldquo;we,&rdquo; &ldquo;our&rdquo;), including
        the website at djinn.gg, the Djinn web application, associated APIs, and all
        smart contracts deployed on the Base blockchain. By connecting a wallet, using
        the API, or otherwise interacting with Djinn, you agree to these Terms. If you
        do not agree, do not use the service.
      </p>
      <p>
        These Terms are supplemented by, and incorporate by reference, the{" "}
        <Link href="/privacy" className="text-slate-900 underline">
          Privacy Policy
        </Link>
        , the{" "}
        <Link href="/risk" className="text-slate-900 underline">
          Risk Disclosure
        </Link>
        , the{" "}
        <Link href="/acceptable-use" className="text-slate-900 underline">
          Acceptable Use Policy
        </Link>
        , and the{" "}
        <Link href="/dmca" className="text-slate-900 underline">
          Copyright / DMCA Policy
        </Link>
        . Each of those documents forms part of the agreement between you and
        Djinn Inc. Where they conflict, the more specific document governs the
        subject matter it addresses.
      </p>

      <div className="not-prose my-6 rounded-xl border-2 border-amber-400 bg-amber-50 px-5 py-4">
        <p className="text-sm font-semibold text-amber-900 mb-1">
          Testnet notice.
        </p>
        <p className="text-sm text-amber-900">
          Djinn currently operates on Base Sepolia, a public test network.
          Tokens on Base Sepolia, including the USDC shown in the interface,
          have no cash value. References in these Terms to &ldquo;USDC,&rdquo;
          &ldquo;deposits,&rdquo; &ldquo;withdrawals,&rdquo; and
          &ldquo;collateral&rdquo; describe protocol mechanics that will apply
          to real assets once Djinn migrates to Base mainnet. Until that
          migration is announced, balances, fees, and payouts in the interface
          are for testing only. Review the{" "}
          <Link href="/risk" className="text-slate-900 underline">
            Risk Disclosure
          </Link>{" "}
          for the full list of risks.
        </p>
      </div>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        1. What Djinn Is
      </h2>
      <p>
        Djinn is a decentralized <strong>information marketplace</strong>. Analysts
        (&ldquo;Geniuses&rdquo;) sell encrypted analytical predictions as an information
        service. Buyers (&ldquo;Idiots&rdquo;) purchase access to those predictions. The
        transaction is a service-level agreement: pay for analytical quality, receive
        compensation if quality is poor.
      </p>
      <p>
        Djinn follows the same structure as a consulting engagement, research subscription,
        or investment newsletter.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        2. What Djinn Is Not
      </h2>
      <p>Djinn is <strong>not</strong> a sportsbook, exchange, broker, or gambling platform. Specifically, Djinn does not:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Accept, facilitate, intermediate, or process any wager or bet</li>
        <li>Match bettors with one another</li>
        <li>Set, quote, or offer odds on any sporting event</li>
        <li>Take any position on any sporting event</li>
        <li>Know whether any user places a bet based on a purchased signal</li>
        <li>Offer, sell, or distribute securities, derivatives, or financial instruments</li>
        <li>Provide custody, clearing, or settlement services for any financial product</li>
      </ul>
      <p>
        These are not policy commitments. They are architectural constraints enforced by
        protocol design. All signal content is encrypted client-side, and the encryption
        key is split across independent validators via Shamir&apos;s Secret Sharing. Djinn
        structurally cannot view signal content. Anyone can verify this from the{" "}
        <a
          href="https://github.com/djinn-inc/djinn"
          target="_blank"
          rel="noopener noreferrer"
          className="text-slate-900 underline"
        >
          open-source client code
        </a>.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        3. Eligibility and Restricted Jurisdictions
      </h2>
      <p>
        You must be at least 18 years old (or the age of majority in your jurisdiction)
        to use Djinn. You are responsible for ensuring that your use of Djinn complies
        with all laws applicable to you in your jurisdiction.
      </p>
      <p>
        <strong>You may not use Djinn if you are located in, a resident of, or a national
        of any jurisdiction subject to comprehensive sanctions by the United States,</strong>{" "}
        including but not limited to: Cuba, Iran, North Korea, Syria, the Crimea, Donetsk,
        and Luhansk regions of Ukraine, or any other jurisdiction designated by the U.S.
        Office of Foreign Assets Control (OFAC). This list may be updated without notice
        as sanctions designations change.
      </p>
      <p>
        You represent and warrant that you are not (a) listed on any U.S. government list
        of prohibited or restricted parties, including the Specially Designated Nationals
        (SDN) list maintained by OFAC, (b) located in or a national of a sanctioned
        jurisdiction, or (c) otherwise prohibited from using the service under applicable
        export control or sanctions laws.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        4. Accounts and Wallets
      </h2>
      <p>
        You connect to Djinn using a blockchain wallet (e.g. Coinbase Smart Wallet,
        MetaMask, or any WalletConnect-compatible wallet). You are solely responsible for
        the security of your wallet, private keys, and any credentials associated with
        your account. Djinn never has access to your private keys.
      </p>
      <p>
        If you lose access to your wallet, you may lose access to your funds and signal
        history. Djinn cannot recover private keys on your behalf.
      </p>
      <p>
        You may not create or use multiple accounts to circumvent rate limits, evade
        enforcement actions, or manipulate the platform. Each natural person or legal
        entity should use a single primary wallet address.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        5. USDC and Platform Balances
      </h2>
      <p>
        Idiots deposit USDC into the Djinn smart contracts to maintain a platform
        balance for purchasing signals. Geniuses deposit USDC as collateral backing
        their service-level agreements. All deposits and withdrawals are executed by
        smart contracts on the Base blockchain and are subject to blockchain transaction
        finality.
      </p>
      <p>
        Djinn does not custody user funds. Funds are held in auditable, open-source smart
        contracts on the Base blockchain. During active settlement periods, collateral
        withdrawals may be temporarily frozen to ensure accurate accounting. This freeze
        typically resolves within one transaction cycle.
      </p>
      <p>
        <strong>Protocol fee.</strong> The smart contracts collect a 0.5% protocol fee on
        each purchase, routed to a treasury address controlled by Djinn Inc. governance.{" "}
        <em>On Base Sepolia (testnet):</em> this fee is collected in mock USDC with no
        cash value, and no real economic transfer occurs.{" "}
        <em>On Base mainnet (once announced):</em> the fee will be collected in real USDC
        and the treasury address will be published at{" "}
        <Link href="/docs" className="text-slate-900 underline">djinn.gg/docs</Link>{" "}
        before any mainnet signal is sold. The fee rate, the treasury address, and any
        future changes to either are governed by a TimelockController with a minimum
        72-hour delay on mainnet, giving users advance notice before economics change.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        6. Signals and Service-Level Agreements
      </h2>
      <p>
        When a Genius creates a signal, they set a fee percentage and SLA Multiplier
        (damages rate). When an Idiot purchases a signal, the fee is automatically
        deducted from their platform balance, and the Genius&apos;s collateral is locked
        proportionally.
      </p>
      <p>
        Once enough signals between a Genius-Idiot pair have resolved outcomes, a cryptographic audit
        computes a Quality Score using secure multi-party computation (MPC). If the
        Quality Score is negative, the Genius&apos;s collateral is slashed: the Idiot
        receives a USDC refund (up to fees paid) plus Djinn Credits for any excess
        damages. If the Quality Score is positive, the Genius retains the fees.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        7. Djinn Credits
      </h2>
      <p>
        Djinn Credits are non-transferable, non-cashable platform credits that function
        as a discount on future signal purchases. Credits do not expire but carry no cash
        value outside the platform. A buyer can never extract more USDC than they
        deposited. Credits are analogous to store credit after a refund.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        8. No Financial or Betting Advice
      </h2>
      <p>
        Nothing on Djinn constitutes financial advice, investment advice, or a
        recommendation to place any wager. Signals are analytical predictions sold as
        information. What you do with purchased information is entirely your decision and
        your responsibility.
      </p>
      <p>
        Past performance of any Genius, as reflected in their Quality Score or track
        record, does not guarantee future results.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        9. Risks
      </h2>
      <p>You acknowledge and accept the following risks:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Smart contract risk:</strong> While audited, smart contracts may contain
          vulnerabilities. Funds deposited into smart contracts are subject to this risk.
          All platform contracts use upgradeable proxy patterns. Contract logic may be
          updated through a governance timelock process. While this enables bug fixes and
          improvements, it means contract behavior can change after you deposit funds.
        </li>
        <li>
          <strong>Blockchain risk:</strong> Transactions on the Base blockchain are
          irreversible. Network congestion, outages, or forks may affect the protocol.
        </li>
        <li>
          <strong>Signal quality risk:</strong> Geniuses may underperform. The SLA
          mechanism provides structured compensation but does not eliminate the risk of
          purchasing poor-quality analysis.
        </li>
        <li>
          <strong>Regulatory risk:</strong> The legal status of information marketplaces,
          cryptocurrency, and related technologies varies by jurisdiction and may change.
        </li>
        <li>
          <strong>Protocol risk:</strong> The Djinn protocol depends on a decentralized
          validator network for MPC computation and outcome verification. Validator
          downtime, consensus failures, or network partitions may delay or affect
          settlement. Signal purchases and decryption depend on validators performing
          secure multi-party computation. If insufficient validators are online, signal
          purchases may temporarily fail or take longer than usual.
        </li>
        <li>
          <strong>Stablecoin risk:</strong> USDC is issued by Circle. Its value, liquidity,
          and redeemability are subject to Circle&apos;s operations and applicable regulations.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        10. Prohibited Conduct
      </h2>
      <p>You agree not to use Djinn to:</p>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10a. General Prohibitions
      </h3>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Violate any applicable local, state, national, or international law or regulation</li>
        <li>Attempt to manipulate track records, Quality Scores, or audit outcomes</li>
        <li>Interfere with the operation of the smart contracts, validators, or miners</li>
        <li>Use automated systems to interact with Djinn in a way that degrades service for other users</li>
        <li>Misrepresent your identity, qualifications, or jurisdiction</li>
        <li>Circumvent any access restrictions, geo-blocking, or rate limits</li>
        <li>Reverse-engineer, decompile, or disassemble the protocol for the purpose of exploiting vulnerabilities (responsible security disclosure is permitted and encouraged)</li>
      </ul>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10b. Financial Crime Prohibitions
      </h3>
      <p>You specifically agree not to use Djinn to:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Launder money</strong> or engage in any activity designed to disguise the
          source, ownership, or destination of funds, including structuring transactions to
          avoid reporting thresholds
        </li>
        <li>
          <strong>Finance terrorism</strong> or provide material support to any person or
          organization designated as a terrorist or terrorist organization by any government
        </li>
        <li>
          <strong>Evade sanctions</strong> or facilitate transactions involving sanctioned
          persons, entities, or jurisdictions
        </li>
        <li>
          <strong>Engage in insider trading</strong> or use material non-public information
          (MNPI) obtained through privileged access to teams, players, officials, leagues,
          or sportsbooks to create or influence signals. This includes but is not limited
          to: injury information not yet public, disciplinary actions, lineup decisions,
          officiating assignments, or any other information that would provide an unfair
          informational advantage
        </li>
        <li>
          <strong>Manipulate sporting events</strong> or use Djinn in connection with
          match-fixing, point-shaving, or any scheme to influence the outcome of a
          sporting event
        </li>
        <li>
          <strong>Engage in market manipulation</strong> including wash trading (buying your
          own signals to inflate track records), coordinated trading to manipulate Quality
          Scores, or any scheme to deceive other users about a Genius&apos;s true performance
        </li>
        <li>
          <strong>Engage in fraud</strong> including creating signals with no analytical
          basis for the purpose of extracting fees, impersonating other Geniuses, or
          misrepresenting signal methodology
        </li>
      </ul>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10c. Enforcement
      </h3>
      <p>
        Djinn reserves the right to restrict access, block wallet addresses, and
        cooperate with law enforcement agencies in the investigation of suspected
        violations. Because Djinn is a decentralized protocol, some enforcement actions
        may be limited to the web application interface while on-chain contracts remain
        permissionless.
      </p>
      <p>
        If you become aware of any prohibited conduct by another user, please report it
        through our contact channels.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        11. API Access
      </h2>
      <p>
        Djinn provides a public API for programmatic access to the protocol. API users
        are subject to the same Terms, including all prohibited conduct provisions. API
        access may be rate-limited to protect service availability. Abuse of the API
        (including but not limited to denial-of-service patterns, scraping for
        competitive intelligence, or circumventing access controls) may result in
        permanent revocation of API access.
      </p>
      <p>
        Developers who build applications on top of the Djinn API are responsible for
        ensuring their applications comply with these Terms and all applicable laws.
        Djinn is not responsible for third-party applications built using the API.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        12. Intellectual Property
      </h2>
      <p>
        The Djinn Protocol is open-source software. The Djinn name, logo, and brand
        assets are the property of Djinn Inc. The open-source license governs the code;
        it does not grant rights to the Djinn brand.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        13. Indemnification
      </h2>
      <p>
        You agree to indemnify, defend, and hold harmless Djinn Inc., its officers,
        directors, employees, agents, and contributors from and against any claims,
        liabilities, damages, losses, costs, or expenses (including reasonable
        attorneys&apos; fees) arising from: (a) your use of the protocol, (b) your
        violation of these Terms, (c) your violation of any applicable law or regulation,
        or (d) any content or signals you create, publish, or distribute through the
        protocol.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14. Limitation of Liability
      </h2>
      <p>
        To the maximum extent permitted by law, Djinn Inc. and its contributors shall not
        be liable for any indirect, incidental, special, consequential, or punitive
        damages, including loss of funds, loss of profits, loss of data, or business
        interruption, arising from your use of the protocol, whether based on warranty,
        contract, tort, or any other legal theory, and whether or not Djinn Inc. has been
        advised of the possibility of such damages.
      </p>
      <p>
        In no event shall the total liability of Djinn Inc. exceed the amount of fees
        you have paid to the protocol in the twelve (12) months preceding the claim.
      </p>
      <p>
        Djinn is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo; without
        warranties of any kind, whether express, implied, or statutory, including but not
        limited to warranties of merchantability, fitness for a particular purpose, and
        non-infringement.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14a. Taxes
      </h2>
      <p>
        You are solely responsible for determining what, if any, taxes apply to
        your use of Djinn, including any gains or losses realized through your
        on-platform activity. Djinn does not withhold taxes, does not issue tax
        forms (1099 or equivalent), and does not provide tax advice. You should
        consult your own tax advisor.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14b. Force Majeure
      </h2>
      <p>
        Djinn Inc. is not liable for any failure or delay in performance caused
        by circumstances beyond its reasonable control, including acts of God,
        natural disaster, war, terrorism, riot, civil disturbance, labor dispute,
        pandemic, government action, network-level attack, extended internet or
        blockchain outage, third-party service failure (including cloud hosting,
        wallet providers, RPC providers, odds data providers), or any other event
        that could not reasonably have been anticipated or prevented.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14c. Electronic Communications
      </h2>
      <p>
        By using Djinn, you consent to receive communications from us
        electronically, including emails to any address you provide, notices
        posted on djinn.gg, and in-product messages. Electronic communications
        satisfy any legal requirement that a communication be in writing. You
        may withdraw this consent by ceasing to use Djinn, but doing so does not
        revoke consent given before withdrawal.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14d. Notice
      </h2>
      <p>
        Any notice to Djinn Inc. under these Terms must be sent to{" "}
        <a href="mailto:legal@djinn.gg" className="text-slate-900 underline">
          legal@djinn.gg
        </a>
        . A notice is considered given on the first business day after
        transmission. Notices to you may be sent to any email address or wallet
        address associated with your account, or posted on djinn.gg, and are
        considered given at the time of transmission or posting.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14e. Responsible Security Disclosure
      </h2>
      <p>
        We welcome responsible security research. If you discover a vulnerability
        in the smart contracts, the validator software, the miner software, the
        SDK, or the djinn.gg front end, please report it privately to{" "}
        <a href="mailto:security@djinn.gg" className="text-slate-900 underline">
          security@djinn.gg
        </a>{" "}
        before any public disclosure. Good-faith research conducted in accordance
        with our{" "}
        <Link href="/acceptable-use" className="text-slate-900 underline">
          Acceptable Use Policy
        </Link>{" "}
        will not result in legal action. A formal bug-bounty program with scope
        and payout tables will be published before mainnet launch.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        15. Dispute Resolution and Arbitration
      </h2>
      <p>
        <strong>Please read this section carefully. It affects your legal rights.</strong>
      </p>
      <p>
        Any dispute, claim, or controversy arising out of or relating to these Terms or
        your use of Djinn (&ldquo;Dispute&rdquo;) shall be resolved through binding
        individual arbitration administered by the American Arbitration Association (AAA)
        under its Commercial Arbitration Rules. The arbitration shall take place in
        Wilmington, Delaware, or at a location mutually agreed upon by the parties.
      </p>
      <p>
        <strong>Class action waiver:</strong> You agree that any Dispute shall be
        resolved only on an individual basis and not as part of any class, consolidated,
        or representative action. The arbitrator may not consolidate more than one
        person&apos;s claims and may not preside over any form of class or representative
        proceeding.
      </p>
      <p>
        <strong>Small claims exception:</strong> Either party may bring an individual
        action in small claims court for Disputes within the court&apos;s jurisdictional
        limits.
      </p>
      <p>
        <strong>Opt-out:</strong> You may opt out of this arbitration provision by
        sending written notice to legal@djinn.gg within 30 days of the date you first
        accepted these Terms (as recorded by the acknowledgment checkbox in the connect
        dialog). The notice must include your wallet address and a statement that you
        wish to opt out of arbitration. If you opt out, Disputes will be resolved in the
        state or federal courts located in Wilmington, Delaware.
      </p>
      <p>
        <strong>Consumer-protection carve-out.</strong> Nothing in this Section limits
        mandatory consumer-protection rights that apply to you by operation of law in
        your country or state of residence. If you are a consumer resident in the
        European Economic Area, the United Kingdom, or Switzerland, you retain the right
        to bring proceedings in, and to rely on the mandatory consumer-protection laws
        of, your country of residence; the arbitration, class waiver, and Delaware forum
        provisions above apply only to the maximum extent permitted by applicable
        mandatory consumer law. You also retain the right to lodge a complaint with your
        local data-protection or consumer authority; nothing in these Terms waives that
        right.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        16. Governing Law
      </h2>
      <p>
        These Terms are governed by the laws of the State of Delaware, United States,
        without regard to conflict of law principles. For consumers resident in the
        European Economic Area, the United Kingdom, or Switzerland, this choice of law
        does not deprive you of the protection of the mandatory provisions of the law of
        your country of habitual residence.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        17. Severability
      </h2>
      <p>
        If any provision of these Terms is held to be unenforceable, that provision will
        be modified to the minimum extent necessary to make it enforceable, and the
        remaining provisions will continue in full force and effect.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        18. Entire Agreement
      </h2>
      <p>
        These Terms, together with the{" "}
        <Link href="/privacy" className="text-slate-900 underline">
          Privacy Policy
        </Link>
        , the{" "}
        <Link href="/risk" className="text-slate-900 underline">
          Risk Disclosure
        </Link>
        , the{" "}
        <Link href="/acceptable-use" className="text-slate-900 underline">
          Acceptable Use Policy
        </Link>
        , and the{" "}
        <Link href="/dmca" className="text-slate-900 underline">
          Copyright / DMCA Policy
        </Link>
        , constitute the entire agreement between you and Djinn Inc. regarding
        your use of the protocol and supersede all prior agreements and
        understandings.
      </p>
      <p>
        Section headings are for convenience only and have no substantive
        effect. If a provision of these Terms grants a right to Djinn Inc., that
        right may be waived only in writing by an authorized representative. No
        third party is intended to be a beneficiary of these Terms, except that
        affiliates, officers, directors, employees, agents, and open-source
        contributors of Djinn Inc. may enforce the indemnity and limitation-of-
        liability provisions on their own behalf.
      </p>
      <p>
        You may not assign or transfer your rights under these Terms without our
        prior written consent. Djinn Inc. may assign these Terms to a successor
        in connection with a merger, acquisition, reorganization, or sale of
        substantially all of its assets. These Terms bind and benefit the
        parties and their permitted successors and assigns.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        19. Modifications
      </h2>
      <p>
        We may update these Terms from time to time. Material changes will be posted on
        this page with an updated date. Continued use of Djinn after changes constitutes
        acceptance of the revised Terms. For material changes that significantly affect
        your rights, we will make reasonable efforts to provide advance notice through the
        web application.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        20. Contact
      </h2>
      <p>
        For questions about these Terms, reach us at{" "}
        <a href="mailto:legal@djinn.gg" className="text-slate-900 underline">
          legal@djinn.gg
        </a>,{" "}
        <a href="https://x.com/djinn_gg" target="_blank" rel="noopener noreferrer" className="text-slate-900 underline">
          @djinn_gg on X
        </a>, or through our{" "}
        <a href="https://discord.com/channels/799672011265015819/1465362098971345010" target="_blank" rel="noopener noreferrer" className="text-slate-900 underline">
          Discord channel
        </a>.
      </p>

      <div className="mt-12 pt-8 border-t border-slate-200">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-700 transition-colors">
          &larr; Back to Djinn
        </Link>
      </div>
    </div>
  );
}
