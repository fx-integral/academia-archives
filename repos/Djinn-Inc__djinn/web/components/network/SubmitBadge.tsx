export interface SubmitBadgeProps {
  runtime?: boolean | null;
  submit?: boolean | null;
}

// Both DJINN_FF_BATCH_SETTLEMENT_HTTP and DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT
// must be ON for a validator to promote shadow_settle from observe-only to
// on-chain submitVote. If only the runtime flag is on, the validator
// participates in MPC batch math but never writes; if only submit is on,
// the runtime 503s and the submit branch never fires. P0-01 closure
// requires 4+ validators at both=ON.
export default function SubmitBadge({ runtime, submit }: SubmitBadgeProps) {
  if (runtime === null || runtime === undefined || submit === null || submit === undefined) {
    return <span className="text-slate-300">-</span>;
  }
  if (runtime && submit) {
    return (
      <span
        className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700"
        title="DJINN_FF_BATCH_SETTLEMENT_HTTP + HTTP_SUBMIT both ON. Validator will call submitVote on-chain after distributed batch settlement."
      >
        submit
      </span>
    );
  }
  if (runtime && !submit) {
    return (
      <span
        className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-700"
        title="DJINN_FF_BATCH_SETTLEMENT_HTTP ON but HTTP_SUBMIT OFF. Participates in MPC batch math but never writes on-chain."
      >
        shadow
      </span>
    );
  }
  if (!runtime && submit) {
    return (
      <span
        className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-700"
        title="DJINN_FF_BATCH_SETTLEMENT_HTTP_SUBMIT ON but HTTP runtime OFF. Submit branch never fires. Flip HTTP ON."
      >
        broken
      </span>
    );
  }
  return (
    <span
      className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-500"
      title="Batch settlement HTTP runtime + submit both OFF (default). Operator must flip both .env flags to participate in P0-01 on-chain quorum."
    >
      off
    </span>
  );
}
