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
  handleCreditsMinted,
  handleCreditsBurned,
} from "../src/credit-ledger";
import {
  CreditsMinted,
  CreditsBurned,
} from "../generated/CreditLedger/CreditLedger";
import { Idiot } from "../generated/schema";

const USER_ADDR = Address.fromString(
  "0x2222222222222222222222222222222222222222"
);

function createCreditsMintedEvent(
  to: Address,
  amount: BigInt
): CreditsMinted {
  let event = changetype<CreditsMinted>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("to", ethereum.Value.fromAddress(to))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createCreditsBurnedEvent(
  from: Address,
  amount: BigInt
): CreditsBurned {
  let event = changetype<CreditsBurned>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("from", ethereum.Value.fromAddress(from))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function seedIdiot(address: Address): void {
  let id = address.toHexString();
  let idiot = new Idiot(id);
  idiot.totalPurchases = BigInt.zero();
  idiot.totalDeposited = BigInt.zero();
  idiot.totalWithdrawn = BigInt.zero();
  idiot.escrowBalance = BigInt.zero();
  idiot.totalFeesPaid = BigInt.zero();
  idiot.totalCreditsUsed = BigInt.zero();
  idiot.creditBalance = BigInt.zero();
  idiot.createdAt = BigInt.fromI32(1600000000);
  idiot.save();
}

describe("Credit Ledger", () => {
  afterEach(() => {
    clearStore();
  });

  test("creates CreditBalance on mint", () => {
    let event = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(event);

    let id = USER_ADDR.toHexString();
    assert.entityCount("CreditBalance", 1);
    assert.fieldEquals("CreditBalance", id, "balance", "100000");
    assert.fieldEquals("CreditBalance", id, "totalMinted", "100000");
  });

  test("accumulates minted credits", () => {
    let event1 = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    let event2 = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(50000)
    );
    handleCreditsMinted(event1);
    handleCreditsMinted(event2);

    let id = USER_ADDR.toHexString();
    assert.fieldEquals("CreditBalance", id, "balance", "150000");
    assert.fieldEquals("CreditBalance", id, "totalMinted", "150000");
  });

  test("handles credit burn", () => {
    let mintEvent = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(mintEvent);

    let burnEvent = createCreditsBurnedEvent(
      USER_ADDR,
      BigInt.fromI32(30000)
    );
    handleCreditsBurned(burnEvent);

    let id = USER_ADDR.toHexString();
    assert.fieldEquals("CreditBalance", id, "balance", "70000");
    assert.fieldEquals("CreditBalance", id, "totalBurned", "30000");
  });

  test("updates Idiot creditBalance when entity exists", () => {
    seedIdiot(USER_ADDR);

    let mintEvent = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(mintEvent);

    let id = USER_ADDR.toHexString();
    assert.fieldEquals("Idiot", id, "creditBalance", "100000");
  });

  test("updates Idiot creditBalance on burn", () => {
    seedIdiot(USER_ADDR);

    let mintEvent = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(mintEvent);

    let burnEvent = createCreditsBurnedEvent(
      USER_ADDR,
      BigInt.fromI32(40000)
    );
    handleCreditsBurned(burnEvent);

    let id = USER_ADDR.toHexString();
    assert.fieldEquals("Idiot", id, "creditBalance", "60000");
  });

  test("updates ProtocolStats totalCreditsMinted", () => {
    let event = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(event);

    assert.fieldEquals(
      "ProtocolStats",
      "1",
      "totalCreditsMinted",
      "100000"
    );
  });

  test("updates ProtocolStats totalCreditsBurned", () => {
    let mintEvent = createCreditsMintedEvent(
      USER_ADDR,
      BigInt.fromI32(100000)
    );
    handleCreditsMinted(mintEvent);

    let burnEvent = createCreditsBurnedEvent(
      USER_ADDR,
      BigInt.fromI32(25000)
    );
    handleCreditsBurned(burnEvent);

    assert.fieldEquals(
      "ProtocolStats",
      "1",
      "totalCreditsBurned",
      "25000"
    );
  });
});
