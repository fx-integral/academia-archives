<div align="center">

# **DogeLayer** ![Subnet 80](https://img.shields.io/badge/Subnet-80-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Bittensor](https://img.shields.io/badge/bittensor-9.10.1-blue.svg)](https://github.com/opentensor/bittensor)

</div>

## Introduction

Bittensor is a decentralized platform that incentivizes production of best-in-class digital commodities. DogeLayer is a Bittensor subnet designed around production of proof-of-work (PoW) mining hashrate for Scrypt algorithm (LTC/DOGE).

It is possible to contribute as a **miner** or a **validator**.

**Miners** contribute Scrypt mining hashrate and earn rewards through two independent systems:
1. **Direct Mining Rewards**: LTC/DOGE earnings from actual mining (distributed via DogeLayer platform)
2. **Alpha tokens**: Subnet-specific tokens for Bittensor-registered miners, representing additional value based on hashpower contribution

**Validators** evaluate miners, ranking (weighting) them by the share-value they've produced over each period of time. This creates a pool where miners can earn immediate mining rewards while miners who are also Bittensor participants also accumulate alpha tokens representing additional value.

**Related Bittensor Documentation**:
- [Introduction to Bittensor](https://docs.learnbittensor.org/learn/introduction)
- [DogeLayer Subnet Information](https://learnbittensor.org/subnets/80)
- [Mining in Bittensor](https://docs.learnbittensor.org/miners/)
- [Frequently asked questions (FAQ)](https://docs-git-permissions-list-bittensor.vercel.app/questions-and-answers)

**Page Contents**:
- [Reward System](#reward-system)
- [Requirements](#requirements)
  - [Miner Requirements](#miner-requirements)
  - [Validator Requirements](#validator-requirements)
- [Installation](#installation)
  - [Common Setup](#common-setup)
  - [Miner Specific Setup](#miner-specific-setup)
  - [Validator Specific Setup](#validator-specific-setup)
- [Subnet Information](#subnet-information)

---

# Reward System

DogeLayer operates a dual reward mechanism:

## 1. Mining Rewards (LTC/DOGE)
Direct cryptocurrency earnings from actual mining with **secondary distribution**:
- **Mining Revenue**: Earn LTC/DOGE from contributing hashpower
- **Platform Collection**: All mining rewards are first collected by the platform
- **Secondary Distribution**: Platform redistributes rewards to miners and validators based on contributions
- **Manual Withdrawal Required**: Both miners and validators must login to DogeLayer website to set withdrawal addresses and submit withdrawal requests
- **Processing Time**: 1-3 business days for withdrawal processing

## 2. Alpha Token Rewards (Bittensor Participants)
Subnet 80 incentivizes miners with additional alpha token rewards:
- **Value-Based Rewards**: Alpha tokens based on the hashpower value you provide
- **Requires Registration**: Only available to miners registered on Bittensor subnet 80
- **Subnet Stake**: Alpha tokens represent stake in the DogeLayer subnet
- **Convertible to TAO**: Can be unstaked to TAO (Bittensor's primary currency)

---

# Requirements

## Miner Requirements

To run a miner with DogeLayer rewards, you will need:

- A Bittensor wallet with coldkey and hotkey
- Scrypt mining hardware (ASICs for LTC/DOGE) OR access to remote hashrate
- Python 3.9 or higher
- The most recent release of [Bittensor SDK](https://pypi.org/project/bittensor/)

**Related Bittensor Documentation**:
- [Wallets, Coldkeys and Hotkeys in Bittensor](https://docs.learnbittensor.org/getting-started/wallets)
- [Miner registration](https://docs.learnbittensor.org/miners/index.md#miner-registration)

## Validator Requirements

To run a DogeLayer validator, you will need:

- A Bittensor wallet with coldkey and hotkey
- Subnet proxy configuration (pre-configured, no setup needed)
- Sufficient TAO stake (minimum ~0.5 TAO, recommended 5-10 TAO)
- Python 3.9 or higher environment
- The most recent release of [Bittensor SDK](https://pypi.org/project/bittensor/)
- Docker & Docker Compose (for containerized deployment)

**Related Bittensor Documentation**:
- [Wallets, Coldkeys and Hotkeys in Bittensor](https://docs.learnbittensor.org/getting-started/wallets)
- [Validator registration](https://docs.learnbittensor.org/validators/index.md#validator-registration)

---

# Installation

## Common Setup

These steps apply to both miners and validators:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dogelayer-ai/dogelayer.git
   cd dogelayer
   ```

2. **Set up and activate a Python virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Upgrade pip:**
   ```bash
   pip install --upgrade pip
   ```

4. **Install the DogeLayer package:**
   ```bash
   pip install -e .
   ```

---

## Miner Specific Setup

After completing the common setup:

### 1. Create a Bittensor Wallet

```bash
# Create coldkey (stores your funds)
btcli wallet new_coldkey --wallet.name my_miner

# Create hotkey (used for mining operations)
btcli wallet new_hotkey --wallet.name my_miner --wallet.hotkey default
```

### 2. Register to Subnet 80

```bash
# Production (Finney mainnet)
btcli subnet register \
  --wallet.name my_miner \
  --wallet.hotkey default \
  --netuid 80 \
  --subtensor.network finney
```

### 3. Connect Your Mining Hardware

Use your **48-character hotkey** as the miner username to connect to the mining pool.

**Miner Username Format:**

DogeLayer supports two formats for miner usernames:

1. **Single rig**: Use your full hotkey
   ```
   5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY
   ```

2. **Multiple rigs**: Add a suffix with dot (`.`) separator
   ```
   5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY.worker01
   5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY.rig1
   ```

**Production Environment (Mainnet)**:
- Pool (Primary): `stratum+tcp://sn80-stratum.dogelayer.ai:3331`
- Pool (Backup): `stratum+tcp://stratum.dogelayer.ai:3331`
- Username: Your hotkey or `hotkey.suffix` for multiple rigs
- Password: `x`

**Important:** All rigs with the same hotkey share the same rewards. The suffix is only used to identify individual rigs.

### 4. Start Mining

Once connected, your mining hardware will:
- Automatically contribute hashrate to the pool
- Have contributions recorded by validators
- Earn TAO rewards sent to your hotkey
- Accumulate LTC/DOGE rewards for withdrawal

### 5. Monitor Your Rewards

**TAO Rewards** (automatic):
```bash
btcli wallet balance --wallet.name my_miner
```

**LTC/DOGE Rewards** (manual withdrawal):
1. Login to DogeLayer website with your Bittensor wallet
2. Set withdrawal addresses for LTC/DOGE
3. View earnings and request withdrawals
4. Processing time: 1-3 business days

**For complete step-by-step instructions**, see the [Miner Setup Guide](./docs/running_miner.md).

---

## Validator Specific Setup

After completing the common setup:

### 1. Create a Bittensor Wallet

```bash
# Create coldkey (stores your funds)
btcli wallet new_coldkey --wallet.name my_validator

# Create hotkey (used for validator operations)
btcli wallet new_hotkey --wallet.name my_validator --wallet.hotkey default
```

### 2. Register to Subnet 80

```bash
# Production (Finney mainnet)
btcli subnet register \
  --wallet.name my_validator \
  --wallet.hotkey default \
  --netuid 80 \
  --subtensor.network finney
```

### 3. Stake TAO (Required)

Validators need sufficient stake to set weights:

```bash
# Stake TAO to your validator
btcli stake add \
  --wallet.name my_validator \
  --wallet.hotkey default \
  --amount 10.0 \
  --subtensor.network finney

# Check stake status
btcli wallet overview \
  --wallet.name my_validator \
  --netuid 80 \
  --subtensor.network finney
```

**Stake Requirements**:
- Minimum: ~0.5 TAO (to meet minimum weight threshold)
- Recommended: 5-10 TAO (for stable operation)
- Validator Permit: May require more depending on competition

### 4. Clone Repository

```bash
# Clone the repository
git clone https://github.com/dogelayer-ai/dogelayer.git
cd dogelayer
```

### 5. Configure Environment

Navigate to the validator directory and create a `.env` file:

```bash
cd dogelayer/validator
cp env.example .env
nano .env
```

Update the `.env` file with your wallet information:

```env
# Bittensor Configuration
NETUID=80
SUBTENSOR_NETWORK=finney
BT_WALLET_NAME=your_wallet_name
BT_WALLET_HOTKEY=your_hotkey_name

# Subnet Proxy Configuration (pre-configured)
# Note: This is a shared API token for all validators
SUBNET_PROXY_API_URL="http://dogelayer-205dd0511d5781e4.elb.ap-southeast-1.amazonaws.com:8889"
SUBNET_PROXY_API_TOKEN="2z1gLMqF6yZuf9G56iCLi5H6lKPMWJ_kgiYp-61_gAI"

# Optional: Database submission
SUBMIT_VALIDATOR_INFO=true
DB_SUBMIT_INTERVAL_SECONDS=300
LOGGING_LEVEL=info
```

**Note for Subnet Owner**: If you are the subnet owner, you need to additionally configure pool parameters to publish pool information to the chain. Regular validators should NOT set these:

```env
# Subnet Owner ONLY - Uncomment if you are the subnet owner
# PROXY_DOMAIN="dogelayer-205dd0511d5781e4.elb.ap-southeast-1.amazonaws.com"
# PROXY_PORT="3331"
# PROXY_HIGH_DIFF_PORT="3332"
# PROXY_API_PORT="8889"
# PROXY_USERNAME="latent-to"
# PROXY_PASSWORD="x"
# PROXY_API_TOKEN="2z1gLMqF6yZuf9G56iCLi5H6lKPMWJ_kgiYp-61_gAI"
```

### 6. Run Validator

**Using Docker Compose (Recommended)**:

1. **Ensure Docker is installed**  
   Get more details here: https://docs.docker.com/engine/install/

2. **Ensure your wallet is accessible**  
   Make sure your Bittensor wallet is in `~/.bittensor/wallets/`

3. **Start the validator**
   ```bash
   docker compose down && docker compose pull && docker compose up -d && docker compose logs -f
   ```

4. **Verify it's running**  
   The validator should start and you should see info logs showing it's scoring miners.

**Common Commands**:

```bash
# View logs
docker compose logs -f

# Stop validator
docker compose down
```

**For complete step-by-step instructions**, see the [Validator Setup Guide](./docs/running_validator.md).


---

## 🏗️ Architecture

```
┌─────────────┐
│   Miners    │ ← Mining hardware/pools
└──────┬──────┘
       │ Submit work & metrics
       ↓
┌─────────────────┐
│ DogeLayer Proxy │ ← Metrics aggregation
└──────┬──────────┘
       │ Query metrics
       ↓
┌─────────────┐
│ Validators  │ ← Calculate weights
└──────┬──────┘
       │ Set weights
       ↓
┌──────────────────┐
│ Bittensor Chain  │ ← TAO rewards
└──────────────────┘
```

### Components

#### Core Module (`dogelayer/core`)
- **Constants**: Network and protocol constants
- **Storage**: Pluggable storage backends (JSON, Redis)
- **Pricing**: Cryptocurrency price APIs
- **Chain Data**: Blockchain data processing
- **Utils**: Common utilities

#### Validator Module (`dogelayer/validator`)
- **Validator**: Main validator logic
- **Storage**: State persistence
- **Connection Manager**: Subtensor connection handling
- **Metrics**: Performance tracking

#### Miner Module (`dogelayer/miner`)
- **Miner**: Main miner logic
- **Storage**: State persistence
- **Pool Integration**: Mining pool connectivity

---

## 📚 Documentation

### Complete Guides
- [Miner Setup Guide](./docs/running_miner.md) - Complete guide for setting up and running a DogeLayer miner
- [Validator Setup Guide](./docs/running_validator.md) - Complete guide for setting up and running a DogeLayer validator



---

# Subnet Information

## Production Environment (Finney Mainnet)
- **Subnet ID (netuid)**: 80
- **Network**: Finney (mainnet)
- **Network Parameter**: `--subtensor.network finney`
- **Algorithm**: Scrypt (LTC/DOGE)
- **Pool Address (Primary)**: `stratum+tcp://sn80-stratum.dogelayer.ai:3331`
- **Pool Address (Backup)**: `stratum+tcp://stratum.dogelayer.ai:3331`
- **Emission**: Dynamic based on contribution

---

## ⚠️ Disclaimer

This software is provided "as is" without warranty of any kind. Use at your own risk.

- Mining involves financial risk
- Always secure your wallets
- Verify all transactions
- Do your own research

---

# Get Involved

- Join the discussion on the [Bittensor Discord](https://discord.com/invite/bittensor) in the Subnet 80 channels.
- Check out the [Bittensor Documentation](https://docs.learnbittensor.org/) for general information about running subnets and nodes.

---

**Full Guides:**
- [DogeLayer Miner Setup Guide](docs/running_miner.md)
- [DogeLayer Validator Setup Guide](docs/running_validator.md)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.
