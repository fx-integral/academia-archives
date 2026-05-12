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
  handleCollateralDeposited,
  handleCollateralWithdrawn,
  handleCollateralLocked,
  handleCollateralReleased,
  handleCollateralSlashed,
} from "../src/collateral";
import {
  Deposited,
  Withdrawn,
  Locked,
  Released,
  Slashed,
} from "../generated/Collateral/Collateral";

const GENIUS_ADDR = Address.fromString(
  "0x1111111111111111111111111111111111111111"
);
const RECIPIENT_ADDR = Address.fromString(
  "0x3333333333333333333333333333333333333333"
);

function createDepositedEvent(genius: Address, amount: BigInt): Deposited {
  let event = changetype<Deposited>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createWithdrawnEvent(genius: Address, amount: BigInt): Withdrawn {
  let event = changetype<Withdrawn>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createLockedEvent(
  signalId: BigInt,
  genius: Address,
  amount: BigInt
): Locked {
  let event = changetype<Locked>(newMockEvent());
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
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createReleasedEvent(
  signalId: BigInt,
  genius: Address,
  amount: BigInt
): Released {
  let event = changetype<Released>(newMockEvent());
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
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  return event;
}

function createSlashedEvent(
  genius: Address,
  amount: BigInt,
  recipient: Address
): Slashed {
  let event = changetype<Slashed>(newMockEvent());
  event.parameters = new Array();
  event.parameters.push(
    new ethereum.EventParam("genius", ethereum.Value.fromAddress(genius))
  );
  event.parameters.push(
    new ethereum.EventParam(
      "amount",
      ethereum.Value.fromUnsignedBigInt(amount)
    )
  );
  event.parameters.push(
    new ethereum.EventParam(
      "recipient",
      ethereum.Value.fromAddress(recipient)
    )
  );
  return event;
}

describe("Collateral", () => {
  afterEach(() => {
    clearStore();
  });

  test("creates CollateralPosition on deposit", () => {
    let event = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(event);

    let posId = GENIUS_ADDR.toHexString();
    assert.entityCount("CollateralPosition", 1);
    assert.fieldEquals("CollateralPosition", posId, "deposited", "5000000");
    assert.fieldEquals("CollateralPosition", posId, "locked", "0");
    assert.fieldEquals("CollateralPosition", posId, "available", "5000000");
  });

  test("handles deposit then lock", () => {
    let depositEvent = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(depositEvent);

    let lockEvent = createLockedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      BigInt.fromI32(2000000)
    );
    handleCollateralLocked(lockEvent);

    let posId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("CollateralPosition", posId, "deposited", "5000000");
    assert.fieldEquals("CollateralPosition", posId, "locked", "2000000");
    assert.fieldEquals("CollateralPosition", posId, "available", "3000000");

    // Genius entity also tracks
    assert.fieldEquals("Genius", posId, "collateralDeposited", "5000000");
    assert.fieldEquals("Genius", posId, "collateralLocked", "2000000");
  });

  test("handles release after lock", () => {
    let depositEvent = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(depositEvent);

    let lockEvent = createLockedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      BigInt.fromI32(2000000)
    );
    handleCollateralLocked(lockEvent);

    let releaseEvent = createReleasedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      BigInt.fromI32(2000000)
    );
    handleCollateralReleased(releaseEvent);

    let posId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("CollateralPosition", posId, "locked", "0");
    assert.fieldEquals("CollateralPosition", posId, "available", "5000000");
  });

  test("handles withdrawal", () => {
    let depositEvent = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(depositEvent);

    let withdrawEvent = createWithdrawnEvent(
      GENIUS_ADDR,
      BigInt.fromI32(3000000)
    );
    handleCollateralWithdrawn(withdrawEvent);

    let posId = GENIUS_ADDR.toHexString();
    assert.fieldEquals("CollateralPosition", posId, "deposited", "2000000");
    assert.fieldEquals("CollateralPosition", posId, "available", "2000000");
  });

  test("handles slash with locked cap", () => {
    // Deposit 5M, lock 3M
    let depositEvent = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(depositEvent);

    let lockEvent = createLockedEvent(
      BigInt.fromI32(1),
      GENIUS_ADDR,
      BigInt.fromI32(3000000)
    );
    handleCollateralLocked(lockEvent);

    // Slash 4M (more than available but less than deposit)
    let slashEvent = createSlashedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(4000000),
      RECIPIENT_ADDR
    );
    handleCollateralSlashed(slashEvent);

    let posId = GENIUS_ADDR.toHexString();
    // deposited = 5M - 4M = 1M
    assert.fieldEquals("CollateralPosition", posId, "deposited", "1000000");
    // locked was 3M but capped at deposited (1M)
    assert.fieldEquals("CollateralPosition", posId, "locked", "1000000");
    assert.fieldEquals("CollateralPosition", posId, "available", "0");
    assert.fieldEquals(
      "CollateralPosition",
      posId,
      "totalSlashed",
      "4000000"
    );

    // Protocol stats
    assert.fieldEquals(
      "ProtocolStats",
      "1",
      "totalCollateralSlashed",
      "4000000"
    );
  });

  test("updates protocol totalCollateralDeposited", () => {
    let event = createDepositedEvent(
      GENIUS_ADDR,
      BigInt.fromI32(5000000)
    );
    handleCollateralDeposited(event);

    assert.fieldEquals(
      "ProtocolStats",
      "1",
      "totalCollateralDeposited",
      "5000000"
    );
  });
});
