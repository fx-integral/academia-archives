import Link from "next/link";

export const metadata = {
  title: "Copyright / DMCA Policy | Djinn",
  description:
    "How to submit a DMCA takedown notice or counter-notice for content accessible through djinn.gg.",
};

export default function Dmca() {
  return (
    <div className="max-w-3xl mx-auto prose prose-slate prose-sm">
      <h1 className="text-3xl font-bold text-slate-900 mb-2">
        Copyright / DMCA Policy
      </h1>
      <p className="text-sm text-slate-400 mb-8">Last updated: April 18, 2026</p>

      <p>
        Djinn Inc. respects the intellectual property rights of others and
        expects users to do the same. This page describes how to submit a notice
        of claimed copyright infringement and how to counter-notice if you
        believe material was removed in error. Our notice-and-takedown process
        is modeled on the Digital Millennium Copyright Act of 1998 (17 U.S.C.
        &sect; 512) (&ldquo;DMCA&rdquo;).
      </p>
      <div className="not-prose my-6 rounded-xl border-2 border-amber-400 bg-amber-50 px-5 py-4">
        <p className="text-sm font-semibold text-amber-900 mb-1">
          Agent registration status.
        </p>
        <p className="text-sm text-amber-900">
          Djinn Inc.&apos;s designated agent has not yet been registered with the
          U.S. Copyright Office&apos;s DMCA Designated Agent directory. We intend
          to complete registration prior to the Djinn Base mainnet launch.
          Until that registration is complete, we follow the notice-and-takedown
          procedure described below as a good-faith dispute channel, but Djinn
          Inc. does not currently claim the 17 U.S.C. &sect; 512(c) safe harbor.
          Rights holders retain all other remedies available under applicable
          law.
        </p>
      </div>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        1. Scope
      </h2>
      <p>
        This policy applies to content hosted by Djinn Inc. at djinn.gg,
        including support messages, profile text, and any other user-submitted
        text or media served from our infrastructure. It does not extend to
        on-chain data on the Base blockchain, the Bittensor network, or any
        third-party front end, which Djinn Inc. does not control and cannot
        modify.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        2. Submitting a DMCA Takedown Notice
      </h2>
      <p>
        If you believe that content on djinn.gg infringes a copyright you own or
        are authorized to enforce, send a notice to our designated agent at the
        address below. To be effective, your notice must include all of the
        following:
      </p>
      <ol className="list-decimal list-inside space-y-1 text-slate-600">
        <li>
          A physical or electronic signature of the copyright owner or a person
          authorized to act on the owner&apos;s behalf
        </li>
        <li>
          Identification of the copyrighted work claimed to be infringed (or, if
          multiple works are covered by a single notice, a representative list)
        </li>
        <li>
          Identification of the material claimed to be infringing, with enough
          specificity for us to locate it (a URL on djinn.gg is strongly
          preferred)
        </li>
        <li>
          Your name, postal address, telephone number, and email address
        </li>
        <li>
          A statement that you have a good-faith belief that the use of the
          material is not authorized by the copyright owner, its agent, or the
          law
        </li>
        <li>
          A statement, under penalty of perjury, that the information in your
          notice is accurate and that you are the copyright owner or authorized
          to act on behalf of the owner
        </li>
      </ol>
      <p>
        Send the notice to our Designated Copyright Agent:
      </p>
      <div className="not-prose my-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
        <div>Djinn Inc.</div>
        <div>Attn: DMCA Agent</div>
        <div>
          Email:{" "}
          <a
            href="mailto:dmca@djinn.gg"
            className="text-slate-900 underline"
          >
            dmca@djinn.gg
          </a>
        </div>
      </div>
      <p>
        A physical address for service and registered designated-agent details
        will be published to the U.S. Copyright Office&apos;s DMCA Designated
        Agent directory prior to mainnet launch. Until then, notices sent to
        the email address above will be processed on a good-faith basis within
        the timeframe described in Section 3.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        3. Consequences of Filing
      </h2>
      <p>
        Upon receipt of a compliant notice, Djinn Inc. will, as promptly as
        reasonably practicable, remove or disable access to the material
        identified and, where possible, notify the user who submitted it.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        4. False Claims
      </h2>
      <p>
        Section 512(f) of the DMCA provides that any person who knowingly
        materially misrepresents that material is infringing may be liable for
        damages, including costs and attorneys&apos; fees. Do not file takedown
        notices for material you do not have the rights to protect.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        5. Counter-Notification
      </h2>
      <p>
        If you believe material was removed in error or misidentification, you
        may send a counter-notice that includes:
      </p>
      <ol className="list-decimal list-inside space-y-1 text-slate-600">
        <li>Your physical or electronic signature</li>
        <li>
          Identification of the material that was removed and the location where
          it appeared before removal
        </li>
        <li>
          A statement, under penalty of perjury, that you have a good-faith
          belief that the material was removed or disabled as a result of
          mistake or misidentification
        </li>
        <li>
          Your name, postal address, telephone number, and a statement that you
          consent to the jurisdiction of the federal court for the judicial
          district in which you reside (or, if outside the United States, for
          the judicial district in which Djinn Inc. may be found), and that you
          will accept service of process from the person who provided the
          original notice, or that person&apos;s agent
        </li>
      </ol>
      <p>
        Counter-notices should be sent to the same address shown above. If we
        receive a valid counter-notice, we may restore the removed material in
        not less than ten (10) nor more than fourteen (14) business days, unless
        we first receive notice from the original notifier that they have filed
        an action seeking a court order to restrain the alleged infringement.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        6. Repeat Infringers
      </h2>
      <p>
        Djinn Inc. will, in appropriate circumstances, terminate access for
        users we determine to be repeat infringers of copyright. What constitutes
        a repeat infringer is decided on a case-by-case basis.
      </p>

      <h2 className="text-xl font-semibold text-slate-900 mt-10 mb-3">
        7. Non-DMCA Copyright Concerns
      </h2>
      <p>
        If your concern is not a DMCA claim (for example, trademark, right of
        publicity, or other claims), please contact{" "}
        <a href="mailto:legal@djinn.gg" className="text-slate-900 underline">
          legal@djinn.gg
        </a>{" "}
        with a description of the issue.
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
