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
  handlePurchaseRecorded,
  handleOutcomeRecorded,
  handleNewCycleStarted,
  handleSettledChanged,
} from "../src/account";
import {
  PurchaseRecorded,
  OutcomeRecorded,
  NewCycleStarted,
  SettledChanged,
} from "../generated/Account/Account";

const GENIUS_ADDR = Address.fromString(
  "0x1111111111111111111111111111111111111111"
);
const IDIOT_ADDR = Address.fromString(
  "0x2222222222222222222222222222222222222222"
);

function createPurchaseRecordedEvent(
  genius: Address,
  idiot: Address,
  purchaseId: BigInt,
  signalCount: BigInt
): PurchaseRecorded {
  let event = changetype<PurchaseRecorded>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "purchaseId",
      ethereum.Value.fromUnsignedBigInt(purchaseId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "signalCount",
      ethereum.Value.fromUnsignedBigInt(signalCount)
    )
  );
  return event;
}

function createOutcomeRecordedEvent(
  genius: Address,
  idiot: Address,
  purchaseId: BigInt,
  outcome: i32
): OutcomeRecorded {
  let event = changetype<OutcomeRecorded>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
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

function createNewCycleStartedEvent(
  genius: Address,
  idiot: Address,
  newCycle: BigInt
): NewCycleStarted {
  let event = changetype<NewCycleStarted>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "newCycle",
      ethereum.Value.fromUnsignedBigInt(newCycle)
    )
  );
  return event;
}

function createSettledChangedEvent(
  genius: Address,
  idiot: Address,
  settled: boolean
): SettledChanged {
  let event = changetype<SettledChanged>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("idiot", ethereum.Value.fromAddress(idiot))
  );
  event.parameters.push(
    new ethereum.EventParam("settled", ethereum.Value.fromBoolean(settled))
  );
  return event;
}

describe("Account", () => {
  afterEach(() => {
    clearStore();
  });

  test("creates Account entity on PurchaseRecorded", () => {
    let event = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(event);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.entityCount("Account", 1);
    assert.fieldEquals("Account", accountId, "signalCount", "1");
    assert.fieldEquals("Account", accountId, "settled", "false");
  });

  test("updates quality score on favorable outcome", () => {
    let purchaseEvent = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(purchaseEvent);

    let outcomeEvent = createOutcomeRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      1 // Favorable
    );
    handleOutcomeRecorded(outcomeEvent);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.fieldEquals("Account", accountId, "qualityScore", "1");
  });

  test("decrements quality score on unfavorable outcome", () => {
    let purchaseEvent = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(purchaseEvent);

    let outcomeEvent = createOutcomeRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      2 // Unfavorable
    );
    handleOutcomeRecorded(outcomeEvent);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.fieldEquals("Account", accountId, "qualityScore", "-1");
  });

  test("void outcome does not change quality score", () => {
    let purchaseEvent = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(purchaseEvent);

    let outcomeEvent = createOutcomeRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      3 // Void
    );
    handleOutcomeRecorded(outcomeEvent);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.fieldEquals("Account", accountId, "qualityScore", "0");
  });

  test("resets account on new cycle", () => {
    let purchaseEvent = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(5)
    );
    handlePurchaseRecorded(purchaseEvent);

    let outcomeEvent = createOutcomeRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      1 // Favorable
    );
    handleOutcomeRecorded(outcomeEvent);

    let newCycleEvent = createNewCycleStartedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(2)
    );
    handleNewCycleStarted(newCycleEvent);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.fieldEquals("Account", accountId, "currentCycle", "2");
    assert.fieldEquals("Account", accountId, "signalCount", "0");
    assert.fieldEquals("Account", accountId, "qualityScore", "0");
    assert.fieldEquals("Account", accountId, "settled", "false");
  });

  test("marks account as settled", () => {
    let purchaseEvent = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(purchaseEvent);

    let settledEvent = createSettledChangedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      true
    );
    handleSettledChanged(settledEvent);

    let accountId =
      GENIUS_ADDR.toHexString() + "-" + IDIOT_ADDR.toHexString();
    assert.fieldEquals("Account", accountId, "settled", "true");
  });

  test("creates Genius and Idiot entities on first account", () => {
    let event = createPurchaseRecordedEvent(
      GENIUS_ADDR,
      IDIOT_ADDR,
      BigInt.fromI32(1),
      BigInt.fromI32(1)
    );
    handlePurchaseRecorded(event);

    assert.entityCount("Genius", 1);
    assert.entityCount("Idiot", 1);
  });
});
