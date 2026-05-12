import {
  test,
  describe,
  clearStore,
  assert,
  newMockEvent,
  afterEach,
} from "matchstick-as";
import { BigInt, Address, ethereum } from "@graphprotocol/graph-ts";
import {
  handleAuditSettled,
  handleEarlyExitSettled,
} from "../src/audit";
import {
  AuditSettled,
  EarlyExitSettled,
} from "../generated/Audit/Audit";

const GENIUS_ADDR = Address.fromString(
  "0x1111111111111111111111111111111111111111"
);
const IDIOT_ADDR = Address.fromString(
  "0x2222222222222222222222222222222222222222"
);

function createAuditSettledEvent(
  genius: Address,
  idiot: Address,
  cycle: BigInt,
  qualityScore: BigInt,
  trancheA: BigInt,
  trancheB: BigInt,
  protocolFee: BigInt
): AuditSettled {
  let event = changetype<AuditSettled>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "cycle",
      ethereum.Value.fromUnsignedBigInt(cycle)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "qualityScore",
      ethereum.Value.fromSignedBigInt(qualityScore)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "trancheA",
      ethereum.Value.fromUnsignedBigInt(trancheA)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "trancheB",
      ethereum.Value.fromUnsignedBigInt(trancheB)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "protocolFee",
      ethereum.Value.fromUnsignedBigInt(protocolFee)
    )
  );
  return event;
}

function createEarlyExitSettledEvent(
  genius: Address,
  idiot: Address,
  cycle: BigInt,
  qualityScore: BigInt,
  creditsAwarded: BigInt
): EarlyExitSettled {
  let event = changetype<EarlyExitSettled>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "cycle",
      ethereum.Value.fromUnsignedBigInt(cycle)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "qualityScore",
      ethereum.Value.fromSignedBigInt(qualityScore)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "creditsAwarded",
      ethereum.Value.fromUnsignedBigInt(creditsAwarded)
    )
  );
  return event;
}

describe("Audit", () => {
  afterEach(() => {
    clearStore();
  });

  test("creates AuditResult on AuditSettled", () => {
    let event = createAuditSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(850),
      BigInt.fromI32(100000),
      BigInt.fromI32(200000),
      BigInt.fromI32(10000)
    );
    handleAuditSettled(event);

    let resultId =
      GENIUS_ADDR.toHexString() +
      "-" +
      IDIOT_ADDR.toHexString() +
      "-1";

    assert.entityCount("AuditResult", 1);
    assert.fieldEquals("AuditResult", resultId, "cycle", "1");
    assert.fieldEquals("AuditResult", resultId, "qualityScore", "850");
    assert.fieldEquals("AuditResult", resultId, "trancheA", "100000");
    assert.fieldEquals("AuditResult", resultId, "trancheB", "200000");
    assert.fieldEquals("AuditResult", resultId, "protocolFee", "10000");
    assert.fieldEquals("AuditResult", resultId, "isEarlyExit", "false");
  });

  test("updates Genius aggregate quality score", () => {
    let event = createAuditSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(850),
      BigInt.fromI32(100000),
      BigInt.fromI32(200000),
      BigInt.fromI32(10000)
    );
    handleAuditSettled(event);

    let geniusId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("Genius", geniusId, "totalAudits", "1");
    assert.fieldEquals(
      "Genius",
      geniusId,
      "aggregateQualityScore",
      "850"
    );
  });

  test("accumulates quality scores across audits", () => {
    let event1 = createAuditSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(500),
      BigInt.fromI32(50000),
      BigInt.fromI32(100000),
      BigInt.fromI32(5000)
    );
    handleAuditSettled(event1);

    let idiot2 = Address.fromString(
      "0x3333333333333333333333333333333333333333"
    );
    let event2 = createAuditSettledEvent(
      GENIUS_ADDR,
      idiot2,
      BigInt.fromI32(1),
      BigInt.fromI32(300),
      BigInt.fromI32(30000),
      BigInt.fromI32(60000),
      BigInt.fromI32(3000)
    );
    handleAuditSettled(event2);

    let geniusId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("Genius", geniusId, "totalAudits", "2");
    assert.fieldEquals(
      "Genius",
      geniusId,
      "aggregateQualityScore",
      "800"
    );
  });

  test("creates AuditResult on EarlyExitSettled", () => {
    let event = createEarlyExitSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(2),
      BigInt.fromI32(600),
      BigInt.fromI32(50000)
    );
    handleEarlyExitSettled(event);

    let resultId =
      GENIUS_ADDR.toHexString() +
      "-" +
      IDIOT_ADDR.toHexString() +
      "-2";

    assert.entityCount("AuditResult", 1);
    assert.fieldEquals("AuditResult", resultId, "isEarlyExit", "true");
    assert.fieldEquals("AuditResult", resultId, "trancheA", "0");
    assert.fieldEquals("AuditResult", resultId, "trancheB", "50000");
    assert.fieldEquals("AuditResult", resultId, "protocolFee", "0");
    assert.fieldEquals("AuditResult", resultId, "qualityScore", "600");
  });

  test("updates ProtocolStats on audit settled", () => {
    let event = createAuditSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(850),
      BigInt.fromI32(100000),
      BigInt.fromI32(200000),
      BigInt.fromI32(10000)
    );
    handleAuditSettled(event);

    assert.fieldEquals("ProtocolStats", "1", "totalAudits", "1");
    assert.fieldEquals("ProtocolStats", "1", "totalProtocolFees", "10000");
  });

  test("updates ProtocolStats on early exit", () => {
    let event = createEarlyExitSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(600),
      BigInt.fromI32(50000)
    );
    handleEarlyExitSettled(event);

    assert.fieldEquals("ProtocolStats", "1", "totalEarlyExits", "1");
  });

  test("ensures Idiot entity exists after audit", () => {
    let event = createAuditSettledEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(850),
      BigInt.fromI32(100000),
      BigInt.fromI32(200000),
      BigInt.fromI32(10000)
    );
    handleAuditSettled(event);

    let idiotId = IDIOT_ADDR.toHexString();
    assert.entityCount("Idiot", 1);
    assert.fieldEquals("Idiot", idiotId, "totalPurchases", "0");
  });
});
