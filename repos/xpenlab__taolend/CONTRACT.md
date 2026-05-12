<div align="center">

# TaoLend

**Decentralized Peer-to-Peer Lending Protocol on Bittensor**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Solidity](https://img.shields.io/badge/Solidity-^0.8.24-orange.svg)](https://soliditylang.org/)

[Website](https://taolend.io)

</div>

---

## 📖 Overview

TaoLend is a trustless peer-to-peer lending protocol on Bittensor that enables:
- **Lenders**: Earn interest on TAO while maintaining liquidity
- **Borrowers**: Access TAO liquidity using subnet ALPHA as collateral, without selling holdings

All operations are secured by smart contracts with cryptographically signed offers (EIP-712).

---

## 🔄 For Lenders

### 1️⃣ Deposit TAO

Deposit TAO into the contract. Your TAO is automatically staked to Bittensor delegate.

**Benefits**:
- ✅ TAO remains liquid and available for lending
- ✅ Withdraw unused TAO anytime (no lock-up)

---

### 2️⃣ Create Loan Offers

Create signed offers specifying your lending terms:

**Offer Parameters**:

| Parameter | Description | Constraints |
|-----------|-------------|-------------|
| **Subnet (netuid)** | Which ALPHA subnet to accept as collateral | Must be > 0 |
| **Max TAO Amount** | Total lending capacity for this offer | In RAO (9 decimals), min 1 TAO |
| **Max ALPHA Price** | Maximum ALPHA price accepted for collateral calculation | Must be < 90% of on-chain price |
| **Daily Interest Rate** | Your earnings rate | 0.01% - 1% per day |
| **Expiration** | Offer validity period | In timestamp |
| **Nonce** | Auto-incremented counter | Current lender nonce |

**⚠️ WARNING: Expiration Management**
- Setting expiration too far in the future can expose you to market risks
- Recommend setting appropriate expiration periods based on market conditions
- **Actively monitor your offers** and cancel them if market conditions change unfavorably
- Canceling offers requires an **on-chain transaction** via `cancel(offer)` or `cancel()` (increment nonce)

**Process**:
1. Sign offer using EIP-712 (cryptographic signature)
2. Offer stored in protocol database
3. No further action needed - contract executes automatically when borrower accepts

**Example**: Lend up to 500 TAO for netuid=2 ALPHA collateral at 0.5% daily interest, valid for 30 days.

---

### 3️⃣ Earn Interest

When borrowers accept your offer:
- TAO automatically transferred from your deposited balance to borrower
- Interest accrues daily: `interest = principal × days × rate / 7200 / 1e9`
- **Platform fee**: 30% of interest (not principal)

**Example Earnings**:
- Loan: 300 TAO at 0.5%/day for 10 days
- Total interest: 15 TAO
- Platform fee: 4.5 TAO (30%)
- **Your earnings: 10.5 TAO**

---

### 4️⃣ Manage Loans

**Request Repayment**:
- Available after 3-day minimum loan duration
- Call `collect(loanId)` to initiate collection
- Borrower has 3-day grace period to repay

**Transfer Loan**:
- Sell your loan position to another lender
- Available after 3 days (or immediately from IN_COLLECTION state)
- Receive principal + accrued interest
- Call `transfer(loanId, newOffer)`

**Seize Collateral**:
- If borrower doesn't repay within grace period
- Call `seize(loanId)` to claim ALPHA collateral
- Available 3 days after collection

---

### 5️⃣ Cancel Offers

**Cancel Specific Offer**:
- Call `cancel(offer)` with offer details

**Cancel All Offers**:
- Call `cancel()` to increment nonce
- Invalidates all existing offers instantly

---

### 6️⃣ Withdraw TAO

Withdraw unused TAO anytime (only TAO not currently lent out).

---

## 🔐 For Borrowers

**⚠️ IMPORTANT PREREQUISITE**: Before borrowing, you **MUST** deposit ALPHA collateral into the contract first.

**Why Deposit is Required**:
- The contract needs to lock your ALPHA as collateral when you borrow
- ALPHA must already be in the contract before calling the `borrow()` function
- This ensures atomic loan execution and collateral security

---

### 1️⃣ Accept Loan Offer

Find a lender's offer and accept it:

**Requirements**:
- Valid signed offer from lender
- Minimum loan amount: 1 TAO
- Sufficient ALPHA collateral: `alphaAmount × offerPrice / 1e9 ≥ taoAmount`
- Lender has available TAO balance
- Offer not expired or canceled

**Process**:
- Call `borrow(offer, taoAmount, alphaAmount)`
- Contract validates all conditions
- ALPHA collateral automatically locked
- TAO instantly transferred to your wallet

---

### 2️⃣ Repay Loan

Repay anytime:

**⚠️ IMPORTANT**: Before repaying, you **MUST** deposit sufficient TAO into the contract first using `depositTao()`. The contract requires TAO to be available in your internal balance (`userAlphaBalance[msg.sender][0]`) to process repayment.

**Repayment Amount**:
```
Elapsed Blocks = Current Block - Start Block
Interest = (Principal × Elapsed Blocks × Daily Rate) / (7200 × 1e9)
Total = Principal + Interest

Or expressed in days:
Days = Elapsed Blocks / 7200
Interest = (Principal × Days × Daily Rate) / 1e9
```

**Upon Repayment**:
- ✅ ALPHA collateral immediately released
- ✅ Loan state becomes REPAID

**Third-Party Repayment**:
- Anyone can repay your loan
- Collateral returns to you (original borrower)

---

### 2️⃣b Repay by Selling Collateral (`repayBySell`)

An alternative repayment method that sells part or all of your ALPHA collateral to cover the repayment, without requiring TAO from your balance.

**Process**:
- Call `repayBySell(loanId, alphaAmount, limitAlphaPrice)`
- Contract sells `alphaAmount` ALPHA collateral → TAO
- TAO proceeds added to your balance, then used for repayment
- Remaining collateral (`collateralAmount - alphaAmount`) returned to you

**Requirements**:
- Only the borrower can call this (not third-party)
- `alphaAmount ≤ collateralAmount`
- After selling, total TAO (existing balance + sale proceeds) must cover full repayment
- `limitAlphaPrice`: Minimum acceptable sell price (floor price, in TAO/ALPHA × 1e9). Reverts if actual sell price is lower.

**Partial TAO top-up scenario**:
```
Repay Amount = 100 TAO (principal + interest)
ALPHA Collateral = 5000 ALPHA, current price ≈ 0.025 TAO/ALPHA

Sell 3800 ALPHA → ≈ 95 TAO proceeds
Existing TAO balance: 5 TAO
Total available: 95 + 5 = 100 TAO ✅ → repayment succeeds
Remaining collateral returned: 1200 ALPHA
```

**Slippage Control**:
- `limitAlphaPrice` is a **floor** price (minimum you accept for selling ALPHA)
- Contract calls `alpha.simSwapAlphaForTao()` to check actual sell price before executing
- Transaction reverts if `actualPrice < limitAlphaPrice`

**Use Cases**:
- Don't have enough TAO in your balance but hold ALPHA collateral
- Want to close a leveraged position entirely by unwinding collateral
- Avoid depositing additional TAO just to repay

---

### 3️⃣ Refinance Loan

Switch to a better offer anytime:

**Process**:
- Call `refinance(loanId, newOffer, newTaoAmount)`
- Old loan repaid (principal + interest)
- New loan created with same collateral
- All in one atomic transaction

**Scenarios**:

**Borrow Less**: Pay difference in TAO ⚠️ *Requires TAO deposited in contract*
```
Old: 300 TAO owed (315 after interest)
New: 250 TAO
→ Pay 65 TAO difference (must have sufficient TAO balance in contract)
```

**Borrow More**: Receive additional TAO
```
Old: 300 TAO owed (315 after interest)
New: 400 TAO
→ Receive 85 TAO (400-315)
```

**Same Amount, Better Rate**: Reduce future interest costs
```
Old: 0.5%/day → New: 0.3%/day
```

---

### 4️⃣ Handle Collection

If lender calls `collect()`:

**Your Options**:
1. **Repay**: Pay principal + interest, get collateral back
2. **Refinance**: Switch to new lender with better terms
3. **Wait**: 3-day grace period before seizure

**Default Consequence**:
- After 3 days, lender can call `seize()`
- All ALPHA collateral transferred to lender
- No further obligation

---

### 5️⃣ Withdraw ALPHA (Optional)

After repaying all loans, withdraw unused ALPHA.

**Important Notes**:
- ⚠️ **EVM-Generated Coldkey Required**: The registered SS58 coldkey address MUST be EVM-generated. Using a non-EVM coldkey may result in withdrawal failures or fund loss.
- **Default Behavior**: `withdrawAlpha` transfers assets to your registered EVM-generated coldkey address by default.

---

## ⚡ Leverage Operations

Leverage operations allow borrowers to create amplified ALPHA positions by borrowing TAO and immediately buying more ALPHA. Two functions are available depending on the starting asset.

> **Admin Prerequisite**: A manager must call `setMaxLevel(netuid, level)` to enable leverage for a subnet. If `subnetMaxLevels[netuid] == 0`, all leverage operations on that subnet are disabled. The level value represents the maximum leverage ratio in percent (e.g., `150` = up to 150% borrow-to-collateral).

---

### `borrowLevel` — Leverage with Existing ALPHA

Use your already-deposited ALPHA as collateral to borrow TAO, which is immediately swapped into more ALPHA, amplifying your position.

**Signature**: `borrowLevel(offer, borrowTaoAmount, alphaAmount, limitAlphaPrice)`

| Parameter | Description |
|-----------|-------------|
| `offer` | Lender's signed offer (same as regular `borrow`) |
| `borrowTaoAmount` | TAO to borrow (RAO units) |
| `alphaAmount` | Your existing ALPHA to use as base collateral |
| `limitAlphaPrice` | Maximum acceptable price for buying ALPHA (ceiling, TAO/ALPHA × 1e9) |

**Flow**:
1. Your `alphaAmount` ALPHA deducted from your balance and locked as base collateral
2. `borrowTaoAmount` TAO withdrawn from lender's balance
3. Contract swaps borrowed TAO → ALPHA on the subnet
4. Loan collateral = your original ALPHA + newly bought ALPHA
5. Loan type: `1` (level borrow)

**Level Check** (enforced on-chain):
```
borrowTaoAmount × PRICE_BASE × 100 ≤ alphaAmount × offer.maxAlphaPrice × maxLevel

Simplified:
borrowTao / (alphaAmount × alphaPrice / PRICE_BASE) ≤ maxLevel / 100

Example (maxLevel = 150):
alphaAmount = 10,000 ALPHA, alphaPrice = 0.02 TAO/ALPHA
Collateral value = 200 TAO
Maximum borrow = 200 × 150% = 300 TAO
```

**Slippage Control**:
- `limitAlphaPrice` is a **ceiling** price (maximum you pay for buying ALPHA)
- Uses `alpha.simSwapTaoForAlpha()` to check price before executing
- Reverts if simulated buy price ≥ `limitAlphaPrice`

**Example**:
```
Start: 10,000 ALPHA in balance, price ≈ 0.02 TAO/ALPHA (collateral value = 200 TAO)
maxLevel = 150 → max borrow = 300 TAO
Borrow 150 TAO → buy ~7,500 ALPHA at market price

Resulting loan:
  Collateral: 17,500 ALPHA (10,000 original + 7,500 bought)
  Debt: 150 TAO + accruing interest
```

---

### `buyLevel` — Leverage Buy ALPHA with TAO

Use your TAO balance as collateral to create a leveraged long ALPHA position. The contract combines your TAO + borrowed TAO to buy ALPHA, which becomes the loan collateral.

**Signature**: `buyLevel(offer, collateralTaoAmount, borrowTaoAmount, limitAlphaPrice)`

| Parameter | Description |
|-----------|-------------|
| `offer` | Lender's signed offer |
| `collateralTaoAmount` | Your TAO to contribute as collateral (from `userAlphaBalance[you][0]`) |
| `borrowTaoAmount` | Additional TAO to borrow from lender |
| `limitAlphaPrice` | Maximum acceptable price for buying ALPHA (ceiling) |

**Flow**:
1. Your `collateralTaoAmount` TAO deducted from your balance
2. `borrowTaoAmount` TAO withdrawn from lender's balance
3. Contract swaps (collateralTao + borrowTao) → ALPHA on the subnet
4. Bought ALPHA becomes the sole loan collateral
5. Loan type: `2` (buy level)

**Level Check** (enforced on-chain):
```
borrowTaoAmount × 100 ≤ collateralTaoAmount × maxLevel

Simplified:
borrowTao / collateralTao ≤ maxLevel / 100

Example (maxLevel = 150):
collateralTao = 100 TAO → maximum borrow = 150 TAO
Total TAO to swap = 100 + 150 = 250 TAO
```

**Slippage Control**: Same as `borrowLevel` — `limitAlphaPrice` is a ceiling price.

**Example**:
```
collateralTao = 100 TAO, maxLevel = 150 → max borrow = 150 TAO
Total = 250 TAO swapped → buy ~12,500 ALPHA at 0.02 TAO/ALPHA

Resulting loan:
  Collateral: 12,500 ALPHA
  Debt: 150 TAO + accruing interest
  Your TAO spent: 100 TAO (collateral)
```

---

### Leverage vs Standard Borrow Comparison

| Feature | `borrow` | `borrowLevel` | `buyLevel` |
|---------|----------|---------------|------------|
| Starting asset | ALPHA | ALPHA | TAO |
| Collateral source | User's ALPHA | User's ALPHA + bought ALPHA | Bought ALPHA only |
| TAO sent to borrower | ✅ Yes | ❌ No (buys ALPHA) | ❌ No (buys ALPHA) |
| Amplifies ALPHA position | ❌ No | ✅ Yes | ✅ Yes |
| Loan type | `0` | `1` | `2` |
| Requires `subnetMaxLevels > 0` | ❌ No | ✅ Yes | ✅ Yes |

---

### Repaying Leverage Loans

Leverage loans can be repaid using either:
1. **`repay(loanId)`** — Pay full TAO repayment amount from your balance (requires pre-deposited TAO)
2. **`repayBySell(loanId, alphaAmount, limitAlphaPrice)`** — Sell collateral ALPHA to cover repayment (see above)

`repayBySell` is the natural way to unwind a leverage position: sell the ALPHA that was bought with borrowed TAO, use the proceeds to repay the loan.

---

## 📊 Loan Lifecycle

![Loan State Diagram](docs/LoanState.png)

**States**:

| State | Description | Duration |
|-------|-------------|----------|
| **OPEN** | Active loan, interest accruing | Minimum 3 days for lender actions |
| **IN_COLLECTION** | Lender requested repayment | 3-day grace period |
| **REPAID** | Successfully repaid | Final state ✓ |
| **CLAIMED** | Collateral seized | Final state ✓ |
| **RESOLVED** | Emergency resolution by manager | Final state ⚠️ |

**Key Transitions**:
- **Borrower can repay anytime**; After 3 days: Lender can collect or transfer
- **IN_COLLECTION**: Borrower can repay; Anyone can transfer; Lender can seize (after 3 days)
- **RESOLVED**: Emergency state when subnet is disabled - manager returns assets to both parties

---

## 📋 Additional Important Notes

### 1. Subnet Deregistration Detection

A subnet is considered **deregistered** when:

**Criteria**: Both `alpha_in_pool` and `alpha_out_pool` fall below **15 days of emission**

**Calculation**:
```
Emission threshold = 15 days × daily emission rate
If (alpha_in_pool < threshold) AND (alpha_out_pool < threshold):
    → Subnet is deregistered
```

**Why 15 days**: This threshold ensures:
- Normal market fluctuations don't trigger false deregistration
- Genuine subnet shutdowns are detected promptly
- Sufficient time buffer to distinguish temporary vs permanent issues

**What happens next**: Once detected, the manager can begin resolving affected loans and ALPHA positions.

---

### 2. Subnet Deregistration and Resolution

In rare cases where a subnet is disabled or deregistered from Bittensor, the protocol manager can manually resolve affected loans using the `resolveLoan()` function.

**When It's Used**:
- Subnet is disabled on the protocol
- Subnet has low ALPHA in pool (most staked ALPHA already withdrawn)
- Loan is in OPEN or IN_COLLECTION state

**What Happens**:
1. Manager calls `resolveLoan(loanId, lenderAmount, borrowerAmount)`
2. Lender receives `lenderAmount` TAO (principal + partial interest compensation)
3. Borrower receives `borrowerAmount` TAO (partial collateral value compensation)
4. Collateral is released from subnet
5. Loan moves to RESOLVED terminal state

**Purpose**:
- Protects both parties when subnet becomes unusable
- Ensures fair distribution of available assets
- Prevents funds from being locked indefinitely
- Maintains protocol integrity during emergencies

**Note**: This is a rare administrative action only used when normal loan operations cannot proceed due to external subnet issues.

---

### 3. Asset Distribution During Resolution

When a subnet is deregistered, the manager resolves loans and ALPHA using assets obtained from unstaking the deregistered subnet's ALPHA collateral.

**Resolution Process**:

1. **Unstake ALPHA**: Manager unstakes deregistered ALPHA from the subnet, receiving TAO in return
2. **Calculate Available TAO**: Contract balance = unstaked TAO from deregistered ALPHA
3. **Distribute to Loans**: For each affected loan, manager calls `resolveLoan(loanId, lenderAmount, borrowerAmount)`:

**Distribution Priority**:

**First Priority - Lender**:
- ✅ Full principal repayment
- ✅ Accrued interest (if sufficient TAO available)
- Lender receives `lenderAmount` TAO

**Second Priority - Borrower**:
- ✅ Remaining TAO (if any after lender is paid)
- Represents partial compensation for lost collateral
- Borrower receives `borrowerAmount` TAO

**Example Resolution**:
```
Loan: 100 TAO principal, 10 TAO interest accrued
Collateral: 5000 ALPHA → unstaked for 120 TAO

Distribution:
- Lender receives: 110 TAO (principal + interest)
- Borrower receives: 10 TAO (remaining balance)
```

**Fair Distribution**:
- Manager determines appropriate split based on:
  - Loan principal and interest owed
  - Available TAO from unstaked ALPHA
  - Protocol fairness guidelines
- Goal: Minimize losses for both parties proportionally

**ALPHA Resolution**:
- Deposited ALPHA (not in loans) is also resolved similarly
- Users receive TAO compensation based on available contract balance
- Manager ensures fair distribution across all affected positions

---

### 4. Third-Party Repayment

**Anyone can repay a loan on behalf of the borrower**:
- ⚠️ The repayer must first deposit sufficient TAO into the contract using `depositTao()`
- The repayer pays both principal and accrued interest
- Collateral is returned to the **original borrower** (not the repayer)
- This allows friends, family, or liquidation services to help borrowers avoid collateral seizure
- The repayer receives no direct benefit except helping the borrower

**Example**: Alice borrows 100 TAO with ALPHA collateral. Bob (a friend) can repay Alice's 110 TAO debt, and Alice receives her ALPHA back.

---

### 5. Transfer Interest Rate Limit (IN_COLLECTION State)

When a loan is in **IN_COLLECTION** state:
- **Anyone can transfer the loan** to a new lender (not just the current lender)
- **Interest rate protection**: The new offer's daily interest rate can be at most **50% higher** than the current offer
- **Purpose**: Protects borrowers from predatory rates during distressed situations
- **Example**:
  - Current offer: 0.5% daily interest
  - Maximum allowed new rate: 0.75% daily interest (0.5% × 1.5)

This prevents exploitation while still allowing market-based loan transfers during collection.

---

### 6. Uncontrollable Risk: Subnet Transfer Restrictions

**Risk**: Subnet owners have the power to disable ALPHA transfers by setting `transfers_enabled = false`.

**Impact on Users**:

**If `transfers_enabled` is set to `false` AFTER you deposit ALPHA**:
- ✅ **Lending continues**: Your deposited ALPHA can still be used as collateral for new loans
- ✅ **Existing loans unaffected**: Ongoing loans continue normally
- ✅ **Borrowing works**: Borrowers can still accept offers using your ALPHA
- ❌ **Withdrawals blocked**: You CANNOT withdraw your ALPHA to your wallet
- ⏳ **Temporary restriction**: Withdrawals remain blocked until the subnet owner re-enables transfers (`transfers_enabled = true`)

**Why This Happens**:
- Subnet owners control transfer permissions at the network level
- This is a Bittensor network feature, not a protocol decision
- The protocol cannot override subnet-level restrictions

**Protection Measures**:
- Monitor subnet governance and owner policies
- Diversify across multiple subnets to reduce concentration risk
- Only deposit ALPHA from subnets with reliable, transparent governance
- Check subnet `transfers_enabled` status before depositing

**Important**: This is an **uncontrollable external risk** inherent to Bittensor's subnet architecture. Users should evaluate subnet governance quality before depositing significant ALPHA amounts.

---

### 7. EVM-Generated Coldkey Registration Requirement

**Critical Requirement**: The registered SS58 coldkey address **MUST** be EVM-generated.

**Why This Matters**:
- ⚠️ **Using a non-EVM coldkey may result in withdrawal failures or fund loss**
- The protocol relies on EVM-to-SS58 address mapping for secure asset transfers
- Non-EVM coldkeys may not have valid reverse mappings, causing transaction failures

**How It Works**:
- When you register, your SS58 coldkey is linked to your EVM address
- `withdrawAlpha()` transfers assets to your registered coldkey by default
- The coldkey must be derivable from an EVM address for transfers to succeed

**How to Generate EVM-Compatible Coldkey**:
1. Generate an EVM private key (32-byte hex)
2. Derive the EVM address (H160) from the private key
3. Convert the EVM address to SS58 format using the Bittensor subnet ID
4. Use this SS58 address as your coldkey when registering

**Verification**:
- Before registering, verify your coldkey is EVM-generated
- Test with small amounts first
- Ensure you control the EVM private key that generates the coldkey

**Important**: Never use coldkeys from non-EVM wallets (e.g., Polkadot.js native keys) for registration, as this may result in **permanent fund loss** during withdrawals.

---

### 8. Technical Implementation Details

This section explains critical technical design decisions in the smart contract implementation.

#### 8.1 ALPHA Deposit Implementation (`depositAlpha`)

**Why `delegatecall` is Used**:

The `_depositAlpha()` function uses `delegatecall` for the first `transferStake` operation (Line 993 in LendingPoolV2.sol):

```solidity
(bool transferSuccess, ) = address(staking).delegatecall(transferData);
```

**This is intentional design**, not a bug:

- `delegatecall` executes the precompiled contract code in the **caller's context** (msg.sender)
- This allows the contract to transfer ALPHA stake **from the user's account** to the contract's coldkey
- Without `delegatecall`, the contract cannot access the user's staked ALPHA on the Bittensor network
- This enables accurate accounting of deposited amounts: ALPHA is transferred from user → contract coldkey, then moved to DELEGATE_HOTKEY

**Two-Step Process**:
1. **First call (delegatecall)**: Transfer stake from user's account to contract coldkey (uses user's permissions)
2. **Second call (call)**: Move stake from contract coldkey to DELEGATE_HOTKEY (uses contract's permissions)

The second operation uses `call` because it moves stake within the contract's own holdings (from one hotkey to another).

---

#### 8.2 Protocol Fee Accounting (`protocolFeeAccumulated`)

**How Protocol Fees Work**:

`protocolFeeAccumulated` is a **pure accounting variable** that tracks protocol fees owed to the platform. It does NOT represent separate funds - the fees are already part of the contract's total balance.

**Accounting Flow**:

When users repay loans in `repay()`, `transfer()`, or `refinance()`:

1. Full `repayAmount` is deducted from borrower's balance
2. Only `repayAmount - protocolFee` is credited to the lender
3. The difference (`protocolFee`) stays within the contract's total balance
4. `protocolFeeAccumulated` increases to track this fee (accounting entry only)

**Why `subnetAlphaBalance[0]` is NOT increased**:

- The protocol fee is **already accounted for** in the system through the deduction
- It was never removed from the contract's total balance
- Increasing `subnetAlphaBalance[0]` would count it twice

**Mathematical Invariant**:
```
sum(userAlphaBalance[user][0]) + protocolFeeAccumulated = subnetAlphaBalance[0]
```

This ensures:
- User balances + accumulated fees = total TAO pool balance
- When `withdrawProtocolFees()` is called, both `protocolFeeAccumulated` and `subnetAlphaBalance[0]` decrease
- The invariant is maintained throughout all operations

---

#### 8.3 CONTRACT_COLDKEY Initialization

**Why Two-Step Initialization is Required**:

`CONTRACT_COLDKEY` cannot be set in the constructor because it must be **derived from the contract's EVM address**.

**The Problem**:
- The SS58 coldkey address can only be generated **after** the contract is deployed
- During constructor execution, the contract address is not yet finalized
- The coldkey derivation requires the deployed contract's EVM address as input

**Protection Mechanisms**:
- ✅ Can only be called once (checks `CONTRACT_COLDKEY == bytes32(0)`)
- ✅ Only owner can call (onlyOwner modifier)
- ✅ Cannot be set to zero address (checks `_coldkey != bytes32(0)`)

**This is not a design flaw** - it's a necessary consequence of the EVM-to-Substrate address mapping architecture in Bittensor's Frontier implementation.

---

#### 8.4 Upgradeable Proxy Pattern

**What is an Upgradeable Proxy**:

The TaoLend protocol uses an upgradeable proxy pattern to allow contract logic updates without changing the deployed contract address or migrating user data.

**Architecture Components**:

1. **Proxy Contract**: Holds all state (storage) and user funds permanently at a fixed address
2. **Implementation Contract**: Contains the business logic (LendingPoolV2.sol) and can be upgraded
3. **Separation of Concerns**: Storage lives in the proxy, logic lives in the implementation

**How It Works**:

```
User → Proxy Contract (storage + funds)
          ↓ delegatecall
       Implementation Contract (logic)
```

- All user interactions go through the proxy address
- The proxy uses `delegatecall` to execute logic from the implementation contract
- `delegatecall` runs implementation code in the proxy's context (using proxy's storage)
- Users never interact directly with the implementation contract

**Upgrade Process**:

When a new version of LendingPoolV2 is ready:

1. **Deploy New Implementation**: New contract is deployed with updated logic
2. **Upgrade Transaction**: Owner calls `upgradeTo(newImplementationAddress)` on the proxy
3. **Instant Switch**: Proxy now delegates to the new implementation
4. **Zero Downtime**: All user data and balances remain unchanged in proxy storage

**Benefits**:

- ✅ **Bug Fixes**: Critical bugs can be patched without fund migration
- ✅ **Feature Additions**: New functionality can be added (e.g., new loan types, improved efficiency)
- ✅ **Storage Preservation**: All user balances, loans, and offers remain intact
- ✅ **Address Continuity**: Contract address never changes, no need to update integrations
- ✅ **Gas Efficiency**: Upgrades don't require migrating state (extremely expensive)

**Security Considerations**:

**Storage Layout Protection**:
- ⚠️ **CRITICAL**: New implementations must preserve existing storage slot layout
- Adding new variables is safe (append to end)
- Changing order, type, or removing variables will corrupt data
- OpenZeppelin's storage gap pattern helps prevent accidents

**Access Control**:
- Only the contract owner (deployer) can upgrade the implementation
- Upgrades are logged in events for transparency
- Time-lock mechanisms can be added for additional security (future enhancement)

**Initialization Protection**:
- Implementation contracts use `initializer` modifier (not `constructor`)
- Prevents re-initialization after upgrades
- `disableInitializers()` in constructor prevents implementation contract misuse

**Current Implementation Type**:

TaoLend uses the **UUPS (Universal Upgradeable Proxy Standard)** pattern:
- Upgrade logic is in the implementation contract (not proxy)
- More gas efficient than Transparent Proxy
- Requires implementation to inherit from `UUPSUpgradeable`
- Less risk of function selector clashes

**Verification**:

Users can verify the current implementation address:
```solidity
// Query the implementation address from the proxy
implementation = proxy.implementation()
```

**Important Notes**:

- The proxy address is the **official contract address** users should interact with
- Implementation contracts are internal infrastructure and should not be called directly
- All documentation and CLI tools reference the proxy address, not implementation
- Upgrades do not affect user private keys, registration status, or deposited funds

**Transparency**:

- All upgrades are announced through official channels before execution
- Upgrade transactions are publicly visible on-chain
- Implementation source code is verified on block explorers
- Community can audit new implementations before/after deployment

This upgrade mechanism ensures TaoLend can evolve and improve while maintaining the highest security standards and protecting user assets.

---

## ✨ Key Features

### 🤝 Trustless Peer-to-Peer

- Direct lender-borrower matching
- EIP-712 signed offers (cryptographically secure)
- Smart contract enforces all terms
- Off-chain offer discovery (zero gas for creation)

### 💎 Dual-Token Efficiency

**For TAO**:
- Lenders earn interest income
- Borrowers access liquidity without selling

**For ALPHA**:
- Remains staked during loan period as collateral
- Borrowers maintain ALPHA positions without selling

### 🔐 Security Guarantees

**Over-Collateralization**:
- ALPHA value > TAO borrowed
- Offer price must be < 90% on-chain price
- Dynamic price oracle from Bittensor

**Smart Contract Protection**:
- Reentrancy guards
- Access control modifiers
- Immutable critical parameters
- State machine enforcement

**Financial Safety**:
- 3-day minimum loan duration
- 3-day grace period before seizure
- Interest rate limits (0.01% - 1% per day)
- Nonce-based replay protection

### ⚡ Flexible Operations

**For Lenders**:
- Set custom interest rates
- Multiple offers for different subnets
- Transfer loans to other lenders
- Instant offer cancellation via nonce

**For Borrowers**:
- Refinance to better terms
- Early repayment (no penalty)
- Auto-deposit collateral feature
- Leverage existing ALPHA to amplify positions (`borrowLevel`)
- Use TAO to create leveraged long ALPHA positions (`buyLevel`)
- Repay by selling collateral ALPHA directly (`repayBySell`)

**Advanced**:
- Loan transfers create secondary market
- Third-party repayment support
- Atomic refinancing (one transaction)
- Auto-deposit collateral feature (no pre-deposit required)
- Leverage operations with configurable per-subnet limits (up to 5×)

---

## 🏦 Fee Structure

**Platform Fee**: 30% of interest earnings
- Applied when lender receives repayment
- Principal always returned in full
- Example: 15 TAO interest → 4.5 TAO fee, 10.5 TAO to lender

**No Fees For**:
- Deposits and withdrawals
- Creating offers (off-chain)
- Canceling offers
- Loan principal repayment

---

## 🔬 Technical Overview

### Core Components

**Smart Contracts**:
- `LendingPoolV2.sol` - Main protocol logic
- `LoanLib.sol` - EIP-712 signature verification
- Bittensor precompiled interfaces (Staking, Transfer, Alpha)

**Dual Address System**:
- EVM Address (H160): User-controlled via private key
- SS58 Mirror: Auto-derived for Subtensor operations
- All operations must go through contract

**Unit Precision**:
- RAO (9 decimals): Contract storage, Bittensor native
- TAO wei (18 decimals): EVM transactions only
- Conversion: `1 TAO = 1 RAO × 10^9`

### Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| Min Loan Amount | 1 TAO | Minimum loan size |
| Platform Fee | 30% | Fee on interest earnings |
| Max ALPHA Price Safety | 90% | Maximum offer ALPHA price vs on-chain |
| Min Daily Rate | 0.01% | Minimum interest rate |
| Max Daily Rate | 1% | Maximum interest rate |
| Min Loan Duration | 3 days | 21,600 blocks on mainnet |
| Grace Period | 3 days | Collection to seizure delay |
| Blocks Per Day | 7,200 | Interest calculation (12s blocks) |

---

## 🔒 User Requirements

### Before Using TaoLend

1. **Register**: Prove control of your SS58 coldkey via signature
2. **Fund Account**: Transfer TAO/ALPHA to your SS58 mirror address
3. **Understand Terms**: Review offer/loan terms carefully
4. **Monitor Positions**: Track loan durations and deadlines

### Best Practices

**For Lenders**:
- ✅ Set realistic collateral ratios (below 90% maximum)
- ✅ Monitor subnet ALPHA prices
- ✅ Use reasonable expiration periods
- ✅ Keep track of active loans

**For Borrowers**:
- ✅ Borrow at least 1 TAO (minimum loan amount)
- ✅ Ensure sufficient collateral before borrowing
- ✅ Plan repayment before deadline
- ✅ Consider refinancing if better offers available
- ✅ Monitor collection notifications

**Security**:
- ⚠️ Never share private keys
- ⚠️ Verify offer signatures before accepting
- ⚠️ Test on testnet first
- ⚠️ Double-check transaction parameters

---

## 🤝 Community

- **Website**: [https://taolend.io](https://taolend.io)
- **GitHub**: [github.com/xpenlab/taolend](https://github.com/xpenlab/taolend)
- **Email**: team@taolend.io

---

## 📜 License

TaoLend is released under the [MIT License](LICENSE).

---

<div align="center">

**Built on Bittensor**

</div>
