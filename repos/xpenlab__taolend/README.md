<div align="center">

# TaoLend

**A Decentralized TAO Lending Protocol on Bittensor**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Solidity](https://img.shields.io/badge/Solidity-^0.8.24-orange.svg)](https://soliditylang.org/)
[![Subnet](https://img.shields.io/badge/Bittensor-SN116-purple.svg)](https://taostats.io/subnets/netuid-116/)

</div>

---

## 📖 Overview

TaoLend is a decentralized lending protocol for the Bittensor ($TAO) ecosystem. It allows users to lend TAO with confidence while borrowers secure loans using subnet ALPHA as collateral. By unlocking TAO liquidity and keeping ALPHA staked within subnets, TaoLend improves both capital efficiency and network security.

Our vision is to advance the TAO-EVM ecosystem, creating deeper integration between Bittensor and the broader decentralized finance landscape, and ultimately bringing greater value to the entire Bittensor network.

---

## 🚀 Features

- **Point-to-Point Lending** - Lenders and borrowers interact directly to establish loans without intermediaries.

- **Flexible Interest Rates** - Lenders define interest rates according to market conditions, creating a competitive lending marketplace.

- **Permissionless** - Lenders and borrowers complete transactions with the smart contract without requiring third-party approval.

- **Bittensor & EVM Integration** - Seamlessly interact with TAO subnets and the EVM ecosystem through precompiled contracts.

- **Incentivized Participation** - Earn rewards for lending and borrowing TAO, increasing TAO liquidity while keeping ALPHA locked across subnets.

- **Leverage Operations** - Borrowers can amplify ALPHA positions using `borrowLevel` (leverage with existing ALPHA) or `buyLevel` (leverage-buy ALPHA with TAO), and unwind positions via `repayBySell` (repay by selling collateral).

---

## ⛏️ Mining Rewards

TaoLend incentivizes actual trading activity by distributing ALPHA rewards to market participants:

### Reward Distribution

- **20% to TAO Depositors**: Users who deposit TAO into the protocol to provide offer liquidity
- **80% to Active Lenders**: Users who actively provide loans to borrowers (based on actual protocol fees earned)

### Participating

To earn mining rewards:
1. **Deposit TAO**: Visit [www.taolend.io](https://www.taolend.io) and deposit TAO to create loan offers
2. **Create Offers**: Lenders create competitive loan offers
3. **Earn Rewards**: Automatically receive ALPHA rewards based on your contribution

**No Command Line Tools Required** - All operations available through the web interface at [www.taolend.io](https://www.taolend.io).

### Reward Distribution Process

**ALPHA Distribution Flow**:

1. **Miner Registration**
   - Subnet owner registers multiple miners on Subnet 116
   - All undistributed ALPHA is allocated to these registered miners

2. **Daily Distribution Schedule**
   - Distribution executes **8 hours after the end of each day** (UTC+8, 08:00 AM)
   - Calculates rewards for the previous day's activity (00:00 - 23:59 UTC)
   - Example: January 15 rewards distributed on January 16 at 08:00 AM

3. **Allocation Calculation**
   - **Deposit rewards (20%)**: Based on historical TAO deposit balances
   - **Lending rewards (80%)**: Based on actual protocol fees earned
   - Excess ALPHA (after deposit + lending + gas) is **permanently burned**

4. **ALPHA Distribution to Users**
   - All allocated ALPHA is deposited into the **LendingPool contract**
   - ALPHA is credited to users' contract balances (`userAlphaBalance[address][netuid]`)
   - Users can withdraw anytime using the `withdrawAlpha()` function

5. **Minimum Transfer Threshold**
   - **Threshold**: 10 ALPHA per address
   - If an allocation < 10 ALPHA, it is **not transferred** immediately
   - Allocations accumulate in the database until total ≥ 10 ALPHA
   - Once accumulated amount ≥ 10 ALPHA, all pending rewards are deposited in a single transaction

**Withdrawal**:
- Visit [www.taolend.io](https://www.taolend.io) to withdraw your earned ALPHA
- Or use the contract's `withdrawAlpha()` function directly
- No minimum withdrawal amount; withdraw anytime

---

## 🔍 Validator Setup

### Prerequisites

Install NodeJS (latest LTS version) and PM2:

```bash
# Install build essentials
sudo apt install build-essential libssl-dev git

# Install NVM (Node Version Manager)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
source ~/.bashrc

# Install NodeJS (latest LTS version)
nvm install --lts
nvm use --lts

# Install TypeScript and PM2
npm install -g typescript ts-node pm2
```

### Installation

Download code and install dependencies:

```bash
# Clone repository
git clone https://github.com/xpenlab/taolend
cd taolend

# Install Python dependencies
pip install -r requirement.txt
```

### Running Validator

Start validator with auto-upgrade:

```bash
pm2 start --name sn116-auto-upgrade python3 -- start_validator.py \
  --wallet.name <your_wallet_name> \
  --wallet.hotkey <your_hotkey>
```

**Parameters**:
- `--wallet.name`: Your Bittensor wallet name
- `--wallet.hotkey`: Your validator hotkey

**Monitoring**:
```bash
# View logs
pm2 logs sn116-auto-upgrade

# Check status
pm2 status
```

---

## ⚖️ Weight Allocation Algorithm

### Overview

Validators distribute weights to miners (lenders and depositors) based on their contribution to the protocol's trading activity.

### Key Principles

1. **Dual-Cap Protection**: Uses minimum of fixed pool cap and TAO emission cap
2. **Proportional Distribution**: Rewards proportional to deposits and protocol fees earned
3. **Priority-Based Allocation**: Deposit > Loan > Gas > Burn (ensures user rewards are always guaranteed)
4. **Anti-Manipulation**: Historical balance sampling prevents gaming deposit rewards
5. **Fee-Based Incentives**: Lending rewards calculated from actual protocol fees earned (30% of interest)

### Allocation Formula

**Total Allocatable ALPHA**:
```
miner_allocatable_alpha = min(
  EPOCH_DAILY_ALPHA × ALLOCATION_RATE × 0.41,  // Fixed pool cap
  total_emission_tao × 0.41 × ALLOCATION_RATE / alpha_price  // TAO emission cap
)
```

**Split into Deposits and Lending**:
```
deposit_max_alpha = miner_allocatable_alpha × 0.20  // 20% to depositors

// Lending: Calculate from actual protocol fees earned with multiplier
lending_alpha_from_fees = (total_protocol_fees × 1.5) / SN116_alpha_price
lending_actual_alpha = min(
  miner_allocatable_alpha × 0.80,    // 80% cap from allocatable pool
  lending_alpha_from_fees             // Total ALPHA calculated from fees
)
```

**Lending Weight Calculation (80%)**:

Total ALPHA available from protocol fees:
```
// Step 1: Sum all protocol fees from repaid loans (in TAO)
total_protocol_fees = sum(loan.protocol_fee for all repaid loans)

// Step 2: Apply lender fee multiplier and convert to ALPHA
lending_alpha_from_fees = (total_protocol_fees × LENDER_FEE_MULTIPLIER) / SN116_alpha_price
                        = (total_protocol_fees × 1.5) / SN116_alpha_price

Where:
- total_protocol_fees: Sum of all protocol fees (in TAO)
- LENDER_FEE_MULTIPLIER: 1.5x multiplier to incentivize active lending
- SN116_alpha_price: Current ALPHA price on Subnet 116 (in TAO/ALPHA)
```

Apply lending cap:
```
lending_actual_alpha = min(
  miner_allocatable_alpha × 0.80,    // 80% cap
  lending_alpha_from_fees             // Available from fees × 1.5
)
```

Each lender receives proportional allocation:
```
lender_alpha_reward = lending_actual_alpha × (lender_protocol_fee / total_protocol_fees)

Where:
- lender_protocol_fee: Protocol fees earned by this lender's loans (in TAO)
- total_protocol_fees: Total protocol fees from all loans (in TAO)
```

**Note**: The 1.5x multiplier means lenders can receive up to 50% more ALPHA than the TAO value of their protocol fees would suggest, incentivizing active lending over passive deposits.

**Deposit Weight Calculation (20%) - Anti-Manipulation**:

Historical balance sampling to prevent gaming:
```
1. Sample blocks every 360 blocks (~1 hour) throughout the epoch
2. For each user, query on-chain balance at all sampled blocks
3. Take MINIMUM balance across all samples as effective balance
4. Calculate proportional allocation:

user_deposit_reward = deposit_max_alpha × (user_min_balance / total_min_balances)
```

**Why minimum balance?**
- Prevents users from temporarily inflating deposits during allocation
- Requires consistent deposits throughout the entire epoch
- Example: Deposit 10 TAO for 23 hours + 1000 TAO for 1 hour → Effective balance = 10 TAO

**Priority-Based Allocation (Gas & Burn)**:
```
// After user allocations (deposit + lending)
remaining = miner_allocatable_alpha - deposit_max_alpha - lending_actual_alpha

if remaining > 0:
    gas_fee = min(calculated_gas_fee, remaining)
    burn_alpha = remaining - gas_fee
else:
    gas_fee = 0
    burn_alpha = 0

// Priority ensures user rewards are never reduced due to gas/burn shortfall
```

### Constants

| Parameter | Value | Description |
|-----------|-------|-------------|
| `EPOCH_DAILY_ALPHA` | 7,200 ALPHA | Fixed daily pool |
| `ALLOCATION_RATE` | 20-50% (configurable) | Percentage of pool distributed |
| `MINER_EMISSION_RATE` | 41% | Miner's share of TAO emission |
| `LENDING_ALLOCATION_RATE` | 80% | Lending share of miner allocation |
| `DEPOSIT_ALLOCATION_RATE` | 20% | Deposit share of miner allocation |
| `PROTOCOL_FEE_RATE` | 30% | Platform fee (30% of interest) |
| `LENDER_FEE_MULTIPLIER` | 1.5x | Multiplier for lending rewards |
| `BALANCE_SAMPLE_INTERVAL` | 360 blocks | Balance sampling interval (~1 hour) |

### Example Calculation

**Scenario**: Daily allocation with 3 loans

**Step 1: Calculate allocatable ALPHA**
```
miner_allocatable_alpha = 1476 ALPHA  (from dual-cap formula)
deposit_max_alpha = 1476 × 0.20 = 295.2 ALPHA
lending_cap = 1476 × 0.80 = 1180.8 ALPHA
```

**Step 2: Calculate lending ALPHA from fees**
```
Loan A: protocol_fee = 10 TAO
Loan B: protocol_fee = 5 TAO
Loan C: protocol_fee = 3 TAO

Total protocol fees = 10 + 5 + 3 = 18 TAO

ALPHA price = 0.01 TAO/ALPHA

lending_alpha_from_fees = (18 × 1.5) / 0.01 = 27 / 0.01 = 2700 ALPHA
```

**Step 3: Apply lending cap**
```
lending_actual_alpha = min(1180.8, 2700) = 1180.8 ALPHA
```

**Step 4: Distribute to lenders proportionally**
```
Lender A: 1180.8 × (10/18) = 656.0 ALPHA
Lender B: 1180.8 × (5/18) = 328.0 ALPHA
Lender C: 1180.8 × (3/18) = 196.8 ALPHA

Total distributed: 656.0 + 328.0 + 196.8 = 1180.8 ALPHA ✓
```

### Benefits

- **Fair Distribution**: Proportional to actual trading activity
- **Sustainable**: Dual-cap prevents over-allocation
- **Secure**: Historical sampling prevents deposit manipulation
- **Guaranteed Rewards**: Priority system ensures user allocations succeed
- **Fee-Based**: Rewards tied to real protocol fees (30% of interest)
- **Incentivized Lending**: 1.5x multiplier rewards active lending
- **Deflationary**: Excess ALPHA burned

---

## 📜 Smart Contract

### [Contract Details](CONTRACT.md)

**Deployed Addresses**:
- **Contract Proxy**: `0x4AF585f3707beAd92DDB868f8Dd3905cada57f2f`
  - SS58: `5HW9AL6KxJ4sH4UBvk1p19sj4xQGH9jBGrSJS9tBPU3yyW9d`
- **Contract Implementation**: `0x626b1b99aEc1Fdf94506F14F20ec8334Cfe080EA`
- **Manager**: `0x55C4F38318485c93418a14fa11D1445d43608708`
- **Miner Coldkey**: `0xFF2C4368C69719388384719cD88925FcE7ee2945`
  - SS58: `5FG5s8aMSNNkyD3nR9EZt2rt2NtCaepWpyZjZL1NueSURmh1`
- **Treasury**: `5GXCSaa98gxaSMbP4iW66nMLu9wat825EsY5D2n4TvfWS87A`

### Contract Architecture

**Core Contracts**:
- **LendingPoolV2.sol** - Main lending pool contract handling deposits, withdrawals, P2P lending, and leverage operations
- **LoanLib.sol** - EIP-712 signature verification for loan offers
- **Staking Interface** - Interfaces with Bittensor's staking precompiled contract
- **Alpha Interface** - ALPHA price oracle integration

**Key Operations**:

| Function | Type | Description |
|----------|------|-------------|
| `borrow` | Borrow | Standard borrow using ALPHA collateral |
| `borrowLevel` | Leverage | Amplify existing ALPHA position by borrowing TAO to buy more ALPHA |
| `buyLevel` | Leverage | Use TAO to leveraged-buy ALPHA (TAO collateral → ALPHA position) |
| `repay` | Repay | Repay loan with TAO from balance |
| `repayBySell` | Repay | Repay by selling ALPHA collateral, no pre-deposited TAO needed |
| `refinance` | Refinance | Switch to a new offer atomically |
| `collect` | Lender | Request repayment from borrower |
| `transfer` | Lender | Sell loan position to another lender |
| `seize` | Lender | Claim collateral after grace period |

---

## 🤝 Community & Support

- **Website**: [https://www.taolend.io](https://www.taolend.io)
- **GitHub**: [github.com/xpenlab/taolend](https://github.com/xpenlab/taolend)
- **Email**: team@taolend.io
- **Subnet**: Bittensor SN116

---

## 📜 License

TaoLend is released under the [MIT License](LICENSE).

---

## ⚠️ Disclaimer

TaoLend is experimental DeFi software. Use at your own risk. Always:
- Test with small amounts first
- Understand the risks of lending and borrowing
- Monitor your positions regularly
- Verify all transaction parameters

The protocol is provided "as is" without warranties. Users are responsible for their own funds and decisions.

---

<div align="center">

**Built on Bittensor | Powered by TAO**

[Website](https://www.taolend.io) | [GitHub](https://github.com/xpenlab/taolend) | [Subnet 116](https://taostats.io/subnets/netuid-116/)

</div>
