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
  handleDeposited,
  handleWithdrawn,
  handleSignalPurchased,
  handleRefunded,
  handleOutcomeUpdated,
} from "../src/escrow";
import {
  Deposited,
  Withdrawn,
  SignalPurchased,
  Refunded,
  OutcomeUpdated,
} from "../generated/Escrow/Escrow";
import { Signal } from "../generated/schema";

const BUYER_ADDR = Address.fromString(
  "0x2222222222222222222222222222222222222222"
);
const GENIUS_ADDR = Address.fromString(
  "0x1111111111111111111111111111111111111111"
);

function createDepositedEvent(user: Address, amount: BigInt): Deposited {
  let event = changetype<Deposited>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("user", ethereum.Value.fromAddress(user))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createWithdrawnEvent(user: Address, amount: BigInt): Withdrawn {
  let event = changetype<Withdrawn>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("user", ethereum.Value.fromAddress(user))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createSignalPurchasedEvent(
  signalId: BigInt,
  buyer: Address,
  purchaseId: BigInt,
  notional: BigInt,
  feePaid: BigInt,
  creditUsed: BigInt,
  usdcPaid: BigInt
): SignalPurchased {
  let event = changetype<SignalPurchased>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam(
      "signalId",
      ethereum.Value.fromUnsignedBigInt(signalId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam("buyer", ethereum.Value.fromAddress(buyer))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "purchaseId",
      ethereum.Value.fromUnsignedBigInt(purchaseId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "notional",
      ethereum.Value.fromUnsignedBigInt(notional)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "feePaid",
      ethereum.Value.fromUnsignedBigInt(feePaid)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "creditUsed",
      ethereum.Value.fromUnsignedBigInt(creditUsed)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "usdcPaid",
      ethereum.Value.fromUnsignedBigInt(usdcPaid)
    )
  );
  return event;
}

function createRefundedEvent(
  genius: Address,
  idiot: Address,
  cycle: BigInt,
  amount: BigInt
): Refunded {
  let event = changetype<Refunded>(newMockEvent());
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
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createOutcomeUpdatedEvent(
  purchaseId: BigInt,
  outcome: i32
): OutcomeUpdated {
  let event = changetype<OutcomeUpdated>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam(
      "purchaseId",
      ethereum.Value.fromUnsignedBigInt(purchaseId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam("outcome", ethereum.Value.fromI32(outcome))
  );
  return event;
}

function seedSignal(signalId: string, geniusAddr: string): void {
  let signal = new Signal(signalId);
  signal.genius = geniusAddr;
  signal.sport = "basketball_nba";
  signal.maxPriceBps = BigInt.fromI32(500);
  signal.slaMultiplierBps = BigInt.fromI32(200);
  // maxNotional + minNotional are non-nullable in schema; populate defaults
  // so seeded signals satisfy the entity's required fields.
  signal.maxNotional = BigInt.fromI32(1000000000);
  signal.minNotional = BigInt.zero();
  signal.expiresAt = BigInt.fromI32(1700000000);
  signal.status = "Active";
  signal.createdAt = BigInt.fromI32(1600000000);
  signal.createdAtBlock = BigInt.fromI32(100);
  let mockEvt = newMockEvent();
  signal.createdAtTx = mockEvt.transaction.hash;
  signal.save();
}

describe("Escrow", () => {
  afterEach(() => {
    clearStore();
  });

  test("creates Idiot entity on deposit", () => {
    let event = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(1000000)
    );
    handleDeposited(event);

    let idiotId = BUYER_ADDR.toHexString();
    assert.entityCount("Idiot", 1);
    assert.fieldEquals("Idiot", idiotId, "escrowBalance", "1000000");
    assert.fieldEquals("Idiot", idiotId, "totalDeposited", "1000000");
  });

  test("accumulates deposits", () => {
    let event1 = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(1000000)
    );
    let event2 = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(500000)
    );
    handleDeposited(event1);
    handleDeposited(event2);

    let idiotId = BUYER_ADDR.toHexString();
    assert.fieldEquals("Idiot", idiotId, "escrowBalance", "1500000");
    assert.fieldEquals("Idiot", idiotId, "totalDeposited", "1500000");
  });

  test("handles withdrawal", () => {
    let depositEvent = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(1000000)
    );
    handleDeposited(depositEvent);

    let withdrawEvent = createWithdrawnEvent(
      BUYER_ADDR,
      BigInt.fromI32(300000)
    );
    handleWithdrawn(withdrawEvent);

    let idiotId = BUYER_ADDR.toHexString();
    assert.fieldEquals("Idiot", idiotId, "escrowBalance", "700000");
    assert.fieldEquals("Idiot", idiotId, "totalWithdrawn", "300000");
  });

  test("creates Purchase entity on SignalPurchased", () => {
    let geniusId = GENIUS_ADDR.toHexString();
    seedSignal("1", geniusId);

    // Give buyer some escrow balance first
    let depositEvent = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(2000000)
    );
    handleDeposited(depositEvent);

    let purchaseEvent = createSignalPurchasedEvent(
      BigInt.fromI32(1),
      BUYER_ADDR,
      BigInt.fromI32(10),
      BigInt.fromI32(1000000),
      BigInt.fromI32(50000),
      BigInt.fromI32(10000),
      BigInt.fromI32(40000)
    );
    handleSignalPurchased(purchaseEvent);

    assert.entityCount("Purchase", 1);
    assert.fieldEquals("Purchase", "10", "signal", "1");
    assert.fieldEquals("Purchase", "10", "notional", "1000000");
    assert.fieldEquals("Purchase", "10", "feePaid", "50000");
    assert.fieldEquals("Purchase", "10", "creditUsed", "10000");
    assert.fieldEquals("Purchase", "10", "usdcPaid", "40000");
    assert.fieldEquals("Purchase", "10", "outcome", "Pending");

    // Idiot stats updated
    let idiotId = BUYER_ADDR.toHexString();
    assert.fieldEquals("Idiot", idiotId, "totalPurchases", "1");
    assert.fieldEquals("Idiot", idiotId, "totalFeesPaid", "50000");
    assert.fieldEquals("Idiot", idiotId, "totalCreditsUsed", "10000");

    // Genius stats updated
    assert.fieldEquals("Genius", geniusId, "totalPurchases", "1");
    assert.fieldEquals("Genius", geniusId, "totalVolume", "1000000");
    assert.fieldEquals("Genius", geniusId, "totalFeesEarned", "50000");

    // Protocol stats updated
    assert.fieldEquals("ProtocolStats", "1", "totalPurchases", "1");
    assert.fieldEquals("ProtocolStats", "1", "totalVolume", "1000000");
    assert.fieldEquals("ProtocolStats", "1", "totalFees", "50000");
  });

  test("refund increases idiot escrow balance", () => {
    let depositEvent = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(500000)
    );
    handleDeposited(depositEvent);

    let refundEvent = createRefundedEvent(
      GENIUS_ADDR,
      BUYER_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(100000)
    );
    handleRefunded(refundEvent);

    let idiotId = BUYER_ADDR.toHexString();
    assert.fieldEquals("Idiot", idiotId, "escrowBalance", "600000");
  });

  test("updates purchase outcome", () => {
    let geniusId = GENIUS_ADDR.toHexString();
    seedSignal("1", geniusId);

    let depositEvent = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(2000000)
    );
    handleDeposited(depositEvent);

    let purchaseEvent = createSignalPurchasedEvent(
      BigInt.fromI32(1),
      BUYER_ADDR,
      BigInt.fromI32(10),
      BigInt.fromI32(1000000),
      BigInt.fromI32(50000),
      BigInt.fromI32(0),
      BigInt.fromI32(50000)
    );
    handleSignalPurchased(purchaseEvent);

    let outcomeEvent = createOutcomeUpdatedEvent(BigInt.fromI32(10), 1);
    handleOutcomeUpdated(outcomeEvent);

    assert.fieldEquals("Purchase", "10", "outcome", "Favorable");
  });

  test("updates protocol uniqueIdiots count", () => {
    let event = createDepositedEvent(
      BUYER_ADDR,
      BigInt.fromI32(1000000)
    );
    handleDeposited(event);

    assert.fieldEquals("ProtocolStats", "1", "uniqueIdiots", "1");
  });
});
