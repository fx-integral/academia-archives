import Link from "next/link";

export const metadata = {
  title: "Privacy Policy | Djinn",
};

export default function Privacy() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">Privacy Policy</h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <p>
        This Privacy Policy describes how the Djinn Protocol (&ldquo;Djinn,&rdquo;
        &ldquo;we,&rdquo; &ldquo;our&rdquo;) handles information when you use the
        website at djinn.gg, the Djinn web application, and associated APIs. Djinn is
        designed to collect as little data as possible.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        1. Information We Do Not Collect
      </h2>
      <p>
        Djinn is a decentralized protocol. By design, we <strong>do not</strong> collect,
        store, or have access to:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Signal content:</strong> All predictions are encrypted client-side
          before leaving your browser. Djinn structurally cannot view signal content.
        </li>
        <li>
          <strong>Private keys or seed phrases:</strong> Your wallet keys never leave your
          device or wallet provider.
        </li>
        <li>
          <strong>Betting activity:</strong> Djinn has no data path connecting signal
          purchases to any wager placed at any sportsbook.
        </li>
        <li>
          <strong>Individual signal outcomes:</strong> Audit settlements use secure
          multi-party computation (MPC). The smart contracts verify aggregate Quality
          Scores without learning which individual signals were favorable or unfavorable.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        2. Information Stored On-Chain
      </h2>
      <p>
        The following information is recorded on the Base blockchain as part of normal
        protocol operation. Blockchain data is public, permanent, and not controlled
        by Djinn:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Wallet addresses associated with signals and purchases</li>
        <li>Encrypted signal blobs and commitment hashes</li>
        <li>Signal metadata (sport, pricing parameters, expiration, decoy lines)</li>
        <li>USDC deposit and withdrawal transactions</li>
        <li>Audit results and aggregate Quality Scores</li>
        <li>MPC-verified settlement records</li>
      </ul>
      <p>
        This data is inherent to blockchain-based protocols and cannot be deleted.
        It is publicly accessible to anyone reading the Base blockchain, with or
        without Djinn.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        3. Information We Process
      </h2>
      <p>
        To operate the web application and enforce our Terms of Service, we process
        the following data:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>IP addresses:</strong> Used for geographic access controls (to enforce
          sanctions compliance) and rate limiting. IP addresses are not stored
          persistently and are not linked to wallet addresses.
        </li>
        <li>
          <strong>API request metadata:</strong> Request timestamps, endpoints accessed,
          and response codes for rate limiting and abuse prevention. This data is retained
          for up to 30 days.
        </li>
      </ul>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        4. Wallet Connection
      </h2>
      <p>
        Djinn uses standard wallet connection protocols (WalletConnect, Coinbase Smart
        Wallet, MetaMask) for authentication. When you connect your wallet, no personal
        information is collected by Djinn. Your wallet address is used solely to identify
        your on-chain activity. If you use Coinbase Smart Wallet, Coinbase processes
        wallet creation and identity verification data under its own privacy policy.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        5. Local Storage
      </h2>
      <p>
        The Djinn web application uses your browser&apos;s local storage (not cookies)
        to store:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>Terms of Service acceptance status</li>
        <li>Cached signal data for performance (not a dependency; can be cleared)</li>
        <li>Wallet connection preferences</li>
      </ul>
      <p>
        Local storage data remains on your device and is not transmitted to any server.
        You can clear it at any time through your browser settings.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        6. Cookies
      </h2>
      <p>
        The Djinn website does not set first-party cookies. Our wallet connection
        providers may set cookies necessary for authentication functionality. We do not
        use cookies for analytics, advertising, or tracking.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        7. Analytics and Tracking
      </h2>
      <p>
        Djinn does not use analytics services (Google Analytics, Mixpanel, etc.).
        We do not track your browsing behavior, page views, or interactions. Our
        hosting provider (Vercel) may collect basic server logs (IP addresses, request
        timestamps) as part of standard web hosting. These logs are subject to{" "}
        <a href="https://vercel.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-slate-900 underline">
          Vercel&apos;s privacy policy
        </a>.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        8. Third-Party Services
      </h2>
      <p>Djinn integrates with the following third-party services:</p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Coinbase Smart Wallet / WalletConnect:</strong> Wallet connection,
          authentication, and optional gas sponsorship
        </li>
        <li>
          <strong>Base (Coinbase L2):</strong> Blockchain for smart contract execution
        </li>
        <li>
          <strong>The Graph:</strong> Decentralized indexing of public on-chain data
        </li>
        <li>
          <strong>Bittensor:</strong> Decentralized validator and miner network for
          MPC computation and attestation
        </li>
        <li>
          <strong>Vercel:</strong> Website and API hosting
        </li>
        <li>
          <strong>The Odds API:</strong> Sports odds data (no user data is shared with
          this provider)
        </li>
      </ul>
      <p>
        Each service operates under its own privacy policy. Djinn does not control the
        data practices of these providers.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        9. Data Retention
      </h2>
      <p>
        Djinn does not operate servers that store persistent user data. On-chain data is
        permanent and immutable by nature. API request metadata (for rate limiting) is
        retained for up to 30 days. Local storage data persists until you clear it.
        Wallet providers retain their own data per their respective retention policies.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        10. Your Rights
      </h2>
      <p>
        Because Djinn collects minimal data, most traditional data rights (access,
        correction, deletion) apply primarily to data held by your wallet provider.
        Contact your wallet provider directly for data requests.
      </p>
      <p>
        On-chain data cannot be modified or deleted due to the immutable nature of
        blockchain technology. This is a fundamental characteristic of decentralized
        protocols, not a policy choice.
      </p>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10a. European Economic Area, United Kingdom, and Switzerland (GDPR / UK GDPR)
      </h3>
      <p>
        If you are in the EEA, UK, or Switzerland, you have the right to: (i)
        access the personal data we hold about you, (ii) request correction of
        inaccurate data, (iii) request deletion of data we control (note that
        on-chain data is not data we control), (iv) restrict or object to
        processing, (v) data portability, and (vi) lodge a complaint with your
        national supervisory authority.
      </p>
      <p>
        Our legal bases for processing the limited data described in Section 3
        are:
      </p>
      <ul className="list-disc list-inside space-y-1 text-slate-600">
        <li>
          <strong>Legitimate interest</strong> (Art. 6(1)(f) GDPR) for rate
          limiting, abuse prevention, and operating the website securely
        </li>
        <li>
          <strong>Legal obligation</strong> (Art. 6(1)(c) GDPR) for geo-blocking
          of sanctioned jurisdictions and responding to law-enforcement requests
        </li>
        <li>
          <strong>Contract performance</strong> (Art. 6(1)(b) GDPR) when we
          process wallet address and transaction metadata to deliver the service
          you have requested
        </li>
      </ul>
      <p>
        You can withdraw consent-based processing at any time without affecting
        processing that occurred before withdrawal. To exercise GDPR rights,
        email{" "}
        <a href="mailto:privacy@djinn.gg" className="text-slate-900 underline">
          privacy@djinn.gg
        </a>
        . We do not currently have an appointed Data Protection Officer because
        we do not meet the Art. 37 thresholds; you may direct all data-protection
        correspondence to the address above.
      </p>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10b. California (CCPA / CPRA)
      </h3>
      <p>
        If you are a California resident, you have the right to: (i) know what
        personal information we collect, use, disclose, and (in principle) sell
        or share; (ii) delete personal information we collect from you, subject
        to exceptions; (iii) correct inaccurate personal information; (iv)
        opt-out of the sale or sharing of personal information; and (v)
        non-discrimination for exercising these rights.
      </p>
      <p>
        In the preceding twelve months, Djinn has <strong>not sold and has not
        shared</strong> personal information as those terms are defined under
        the CCPA/CPRA. We do not engage in cross-context behavioral advertising.
        We do not knowingly collect or process sensitive personal information
        beyond the limited operational data described in Section 3. We do not
        use automated decision-making that produces legal or similarly
        significant effects.
      </p>
      <p>
        To exercise CCPA/CPRA rights, email{" "}
        <a href="mailto:privacy@djinn.gg" className="text-slate-900 underline">
          privacy@djinn.gg
        </a>
        . You may designate an authorized agent to act on your behalf; we will
        require reasonable verification of both your identity and the
        agent&apos;s authority.
      </p>

      <h3 className="text-base font-semibold text-slate-800 mt-6 mb-2">
        10c. Other Jurisdictions
      </h3>
      <p>
        Several other U.S. states (including Virginia, Colorado, Connecticut,
        Utah, and Texas) have enacted data-privacy statutes that grant rights
        similar to the CCPA. Where those statutes apply to you and are not
        preempted, you may exercise equivalent rights by contacting us at the
        same address above. We respond within the timeframes required by the
        applicable statute.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        11. International Data Transfers
      </h2>
      <p>
        The Djinn web application is hosted on Vercel&apos;s global infrastructure. API
        requests may be processed in any region where Vercel operates. The Base
        blockchain is a global, decentralized network without a single geographic
        location. By using Djinn, you consent to the processing of the limited data
        described above in any jurisdiction where our infrastructure providers operate.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        12. Children
      </h2>
      <p>
        Djinn is not intended for anyone under 18 years of age. We do not knowingly
        collect information from children.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        13. Changes
      </h2>
      <p>
        We may update this Privacy Policy from time to time. Changes will be posted on
        this page with an updated date.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        14. Contact
      </h2>
      <p>
        For privacy questions, reach us at{" "}
        <a href="mailto:privacy@djinn.gg" className="text-slate-900 underline">
          privacy@djinn.gg
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
