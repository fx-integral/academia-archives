export const CANONICAL_OV = "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5".toLowerCase();

export interface OvBadgeProps {
  registered?: boolean | null;
  contract?: string | null;
  diagnosis?: string | null;
}

export default function OvBadge({ registered, contract, diagnosis }: OvBadgeProps) {
  // registered=true on a stale contract (e.g. UID 213 voting into 0x4b140aA)
  // is a silent quorum killer: the validator thinks it's fine but its votes
  // go to a contract nobody reads. Surface this regardless of the reg flag.
  if (contract && contract.toLowerCase() !== CANONICAL_OV) {
    const label = registered === true ? "stale contract" : diagnosis === "stale_env_override" ? "stale env" : "stale";
    return (
      <span
        className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-700"
        title={`Voting into stale OV contract ${contract}. Canonical is ${CANONICAL_OV}.`}
      >
        {label}
      </span>
    );
  }
  if (registered === true) {
    return (
      <span
        className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700"
        title="Registered on canonical OutcomeVoting"
      >
        &#10003;
      </span>
    );
  }
  if (registered === false) {
    const label = diagnosis === "missing_bootstrap" ? "missing" : "off";
    const title =
      diagnosis === "missing_bootstrap"
        ? "Signer is not registered on canonical OutcomeVoting"
        : "settlement_registered=false";
    return (
      <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-700" title={title}>
        {label}
      </span>
    );
  }
  return <span className="text-slate-300">-</span>;
}
