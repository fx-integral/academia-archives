import {
  test,
  describe,
  clearStore,
  assert,
  newMockEvent,
  afterEach,
  beforeEach,
  createMockedFunction,
} from "matchstick-as";
import { BigInt, Address, ethereum } from "@graphprotocol/graph-ts";
import {
  handleSignalCommitted,
  handleSignalCancelled,
  handleSignalStatusUpdated,
} from "../src/signal-commitment";
import {
  SignalCommitted,
  SignalCancelled,
  SignalStatusUpdated,
} from "../generated/SignalCommitment/SignalCommitment";

const GENIUS_ADDR = Address.fromString(
  "0x1111111111111111111111111111111111111111"
);

// matchstick's newMockEvent() defaults to this address as event.address.
// Used to register contract-call mocks in the same address space the
// handler reads from.
const MOCK_CONTRACT_ADDR = Address.fromString(
  "0xA16081F360e3847006dB660bae1c6d1b2e17eC2A"
);

// handleSignalCommitted does a tryCall("isV2Signal", ...) for backward
// compat with v1 signals; without an explicit mock matchstick errors
// instead of returning reverted=true. Register a false-return for
// signalIds 1..10 so the v1 path is taken in tests.
function mockIsV2SignalFalse(signalId: i32): void {
  createMockedFunction(
    MOCK_CONTRACT_ADDR,
    "isV2Signal",
    "isV2Signal(uint256):(bool)"
  )
    .withArgs([ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(signalId))])
    .returns([ethereum.Value.fromBoolean(false)]);
}

function createSignalCommittedEvent(
  signalId: BigInt,
  genius: Address,
  sport: string,
  maxPriceBps: BigInt,
  slaMultiplierBps: BigInt,
  maxNotional: BigInt,
  expiresAt: BigInt
): SignalCommitted {
  let event = changetype<SignalCommitted>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam(
      "signalId",
      ethereum.Value.fromUnsignedBigInt(signalId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam("sport", ethereum.Value.fromString(sport))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "maxPriceBps",
      ethereum.Value.fromUnsignedBigInt(maxPriceBps)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "slaMultiplierBps",
      ethereum.Value.fromUnsignedBigInt(slaMultiplierBps)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "maxNotional",
      ethereum.Value.fromUnsignedBigInt(maxNotional)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "expiresAt",
      ethereum.Value.fromUnsignedBigInt(expiresAt)
    )
  );
  return event;
}

function createSignalCancelledEvent(
  signalId: BigInt,
  genius: Address
): SignalCancelled {
  let event = changetype<SignalCancelled>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam(
      "signalId",
      ethereum.Value.fromUnsignedBigInt(signalId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  return event;
}

function createSignalStatusUpdatedEvent(
  signalId: BigInt,
  newStatus: i32
): SignalStatusUpdated {
  let event = changetype<SignalStatusUpdated>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam(
      "signalId",
      ethereum.Value.fromUnsignedBigInt(signalId)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "newStatus",
      ethereum.Value.fromI32(newStatus)
    )
  );
  return event;
}

describe("Signal Commitment", () => {
  beforeEach(() => {
    // Pre-register isV2Signal mocks for the signalIds used in tests.
    mockIsV2SignalFalse(1);
    mockIsV2SignalFalse(2);
  });

  afterEach(() => {
    clearStore();
  });

  test("creates Signal and Genius entities on SignalCommitted", () => {
    let event = createSignalCommittedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      "basketball_nba",
      BigInt.fromI32(500),
      BigInt.fromI32(200),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );

    handleSignalCommitted(event);

    assert.entityCount("Signal", 1);
    assert.fieldEquals("Signal", "1", "sport", "basketball_nba");
    assert.fieldEquals("Signal", "1", "status", "Active");
    assert.fieldEquals("Signal", "1", "maxPriceBps", "500");
    assert.fieldEquals("Signal", "1", "slaMultiplierBps", "200");
    assert.fieldEquals("Signal", "1", "expiresAt", "1700000000");

    let geniusId = GENIUS_ADDR.toHexString();
    assert.entityCount("Genius", 1);
    assert.fieldEquals("Genius", geniusId, "totalSignals", "1");
    assert.fieldEquals("Genius", geniusId, "activeSignals", "1");
  });

  test("increments signal counts on multiple signals", () => {
    let event1 = createSignalCommittedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      "football_nfl",
      BigInt.fromI32(300),
      BigInt.fromI32(100),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );
    let event2 = createSignalCommittedEvent(
      BigInt.fromI32(2),
      GENIUS_ADDR,
      "basketball_nba",
      BigInt.fromI32(400),
      BigInt.fromI32(150),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );

    handleSignalCommitted(event1);
    handleSignalCommitted(event2);

    let geniusId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("Genius", geniusId, "totalSignals", "2");
    assert.fieldEquals("Genius", geniusId, "activeSignals", "2");
  });

  test("updates ProtocolStats totalSignals", () => {
    let event = createSignalCommittedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      "hockey_nhl",
      BigInt.fromI32(500),
      BigInt.fromI32(200),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );

    handleSignalCommitted(event);

    assert.fieldEquals("ProtocolStats", "1", "totalSignals", "1");
    assert.fieldEquals("ProtocolStats", "1", "uniqueGeniuses", "1");
  });

  test("cancels a signal and decrements active count", () => {
    let commitEvent = createSignalCommittedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      "basketball_nba",
      BigInt.fromI32(500),
      BigInt.fromI32(200),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );
    handleSignalCommitted(commitEvent);

    let cancelEvent = createSignalCancelledEvent(BigInt.fromI32(1), GENIUS_ADDR);
    handleSignalCancelled(cancelEvent);

    assert.fieldEquals("Signal", "1", "status", "Cancelled");
    let geniusId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("Genius", geniusId, "activeSignals", "0");
  });

  test("updates signal status from Active to Cancelled", () => {
    let commitEvent = createSignalCommittedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      "baseball_mlb",
      BigInt.fromI32(500),
      BigInt.fromI32(200),
      BigInt.fromI32(1000000000), BigInt.fromI32(1700000000)
    );
    handleSignalCommitted(commitEvent);

    let statusEvent = createSignalStatusUpdatedEvent(BigInt.fromI32(1), 1);
    handleSignalStatusUpdated(statusEvent);

    assert.fieldEquals("Signal", "1", "status", "Cancelled");
    let geniusId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("Genius", geniusId, "activeSignals", "0");
  });

  test("ignores cancel for non-existent signal", () => {
    let cancelEvent = createSignalCancelledEvent(
      BigInt.fromI32(999),
      GENIUS_ADDR
    );
    handleSignalCancelled(cancelEvent);

    assert.entityCount("Signal", 0);
  });
});
