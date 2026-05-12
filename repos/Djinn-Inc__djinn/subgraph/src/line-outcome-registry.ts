// v1747 Phase 5a: LineOutcomeRegistry subgraph mappings.
//
// Every per-line attestation, finalization, and force-void emits a
// canonical row keyed by lineHash. The web /verify/[lineHash] page reads
// a single Line entity (with its derived attestations[]) to render the
// public verifiability proof: who signed, what outcome, when finalized.
//
// Content fields (sport / event_id / market / side / line_value) are NOT
// stored on chain by LineOutcomeRegistry — they live in
// SignalCommitment.decoyLines and the canonical-string preimage is
// reconstructable client-side. The subgraph stores only the chain-
// observable trace.

import { BigInt, Bytes } from "@graphprotocol/graph-ts";
import {
  LineAttested,
  LineFinalized,
  LineForceVoided,
} from "../generated/LineOutcomeRegistry/LineOutcomeRegistry";
import { Line, LineAttestation } from "../generated/schema";

// Maps the Solidity Outcome enum (uint8) to GraphQL enum string.
function outcomeToString(outcome: i32): string {
  if (outcome == 0) return "Pending";
  if (outcome == 1) return "Favorable";
  if (outcome == 2) return "Unfavorable";
  if (outcome == 3) return "Void";
  return "Pending";
}

function getOrCreateLine(lineHash: Bytes): Line {
  let id = lineHash.toHexString();
  let line = Line.load(id);
  if (line == null) {
    line = new Line(id);
    line.outcome = "Pending";
    line.forceVoided = false;
  }
  return line;
}

export function handleLineAttested(event: LineAttested): void {
  let line = getOrCreateLine(event.params.lineHash);
  line.save();

  let attestor = event.params.attestor;
  // Composite id: lineHash-attestor. One row per (line, signer); the
  // contract enforces uniqueness via attestation[lineHash][signer].
  let id =
    event.params.lineHash.toHexString() + "-" + attestor.toHexString();
  let att = new LineAttestation(id);
  att.line = line.id;
  att.attestor = attestor;
  att.outcome = outcomeToString(event.params.outcome);
  att.block = event.block.timestamp;
  att.blockNumber = event.block.number;
  att.tx = event.transaction.hash;
  att.save();
}

export function handleLineFinalized(event: LineFinalized): void {
  let line = getOrCreateLine(event.params.lineHash);
  line.outcome = outcomeToString(event.params.outcome);
  // uint64 is decoded as BigInt by graph-ts; assign directly.
  line.finalizedAt = event.params.finalizedAt;
  line.finalizedAtBlock = event.block.number;
  line.finalizedAtTx = event.transaction.hash;
  line.save();
}

export function handleLineForceVoided(event: LineForceVoided): void {
  // forceVoid emits both LineForceVoided and LineFinalized in the contract;
  // this handler captures the operator-supplied reason and the void flag.
  let line = getOrCreateLine(event.params.lineHash);
  line.forceVoided = true;
  line.voidReason = event.params.reason;
  line.save();
}
