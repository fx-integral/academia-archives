# Beam Validator

Validators verify bandwidth proofs and set weights on the Bittensor chain.

## Prerequisites

- Python 3.10+
- Bittensor wallet with registered hotkey

## Installation

```bash
# From repository root
pip install -e ".[validator]"
```

## Quick Start

```bash
# Run validator on testnet (single command); cwd should be repository root
cd neurons/validator && \
BEAM_VALIDATOR_WALLET_NAME=your_coldkey \
BEAM_VALIDATOR_WALLET_HOTKEY=your_hotkey \
BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore-dev.b1m.ai \
python main.py
```

## Configuration

Settings use the `BEAM_VALIDATOR_*` prefix (see [`core/config.py`](core/config.py)). Shared subnet env vars intentionally use **`BEAM_`** without the extra prefix:

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `BEAM_VALIDATOR_WALLET_NAME` | Bittensor coldkey name | `default` |
| `BEAM_VALIDATOR_WALLET_HOTKEY` | Bittensor hotkey name | `default` |
| `BEAM_VALIDATOR_WALLET_PATH` | Wallet directory | `~/.bittensor/wallets` |
| `BEAM_VALIDATOR_SUBNET_CORE_URL` | BeamCore HTTP base for validator routes | `http://localhost:8080` |
| `BEAM_SUBNET_CORE_URL` | Alternate BeamCore base (read before settings load, e.g. UID bootstrap) | — |
| `BEAM_SUBTENSOR_NETWORK` | `test` or `finney` | `test` |
| `BEAM_NETUID` | Subnet UID | `304` |

## Running

### Direct Python Command

```bash
# From repository root
cd neurons/validator

# Testnet
BEAM_VALIDATOR_WALLET_NAME=your_coldkey \
BEAM_VALIDATOR_WALLET_HOTKEY=your_hotkey \
BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore-dev.b1m.ai \
python main.py

# Mainnet
BEAM_VALIDATOR_WALLET_NAME=your_coldkey \
BEAM_VALIDATOR_WALLET_HOTKEY=your_hotkey \
BEAM_VALIDATOR_SUBNET_CORE_URL=https://beamcore.b1m.ai \
BEAM_SUBTENSOR_NETWORK=finney \
BEAM_NETUID=105 \
python main.py
```

### Using .env File

```bash
# Copy and edit .env file
cp ../../.env.example .env
# Edit .env with your wallet and network settings

# Run
cd neurons/validator
python main.py
```

### Using Helper Script (if available)

```bash
./scripts/run_validator.sh [testnet|mainnet]
```

## Network Endpoints

| Network | SubnetCore URL              |
| ------- | --------------------------- |
| Testnet | https://beamcore-dev.b1m.ai |
| Mainnet | https://beamcore.b1m.ai     |

---

# Validator Scoring Guide

## Overview

Validators score orchestrators based on metrics fetched from BeamCore API.
All operational data flows through BeamCore - validators do NOT maintain independent state.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BEAMCORE                                       │
│                    (Source of Truth)                                     │
│                                                                          │
│  Persists transfers, tasks, proofs, weights, orchestrator state         │
│                                                                          │
│  Validator client paths (see SubnetCoreClient):                          │
│    GET  /validators/orchestrators                                        │
│    GET  /validators/weights/{epoch}                                      │
│    GET/POST /pob/* (latest epoch, list, verify)                          │
│    POST /validators/scores | /validators/weights | /validators/heartbeat│
│    GET  /config/uid-ranges (startup bootstrap)                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP API
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          VALIDATORS                                      │
│                                                                          │
│   1. Fetch metrics from BeamCore API                                    │
│   2. Compute SLA scores using standard formula                          │
│   3. (Optional) Apply local modifiers                                   │
│   4. Set weights on Bittensor chain                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

## Metrics from BeamCore

Validators consume orchestrator summaries and proofs through [`clients/subnet_core_client.py`](clients/subnet_core_client.py):

- **`GET /validators/orchestrators`** — primary orchestrator leaderboard-style payload used when scoring miners.
- **`GET /validators/weights/{epoch}`** — optional recommended-weight hints from BeamCore PRISM dashboards.
- **`GET /pob`**, **`GET /pob/unverified`**, **`POST /pob/{proof_id}/verify`**, **`GET /pob/latest-epoch`** — Proof-of-bandwidth ingestion and validator attestation loops.

Historical README sections referenced `GET /validators/work-summaries`, `/validators/orchestrators/{hotkey}/workers`, `/validators/epoch/{epoch}/payments`, and `/validators/canary/*`. Those paths are **not** part of the stable BeamCore surface or the bundled client—derive worker/payment insights from orchestrator payloads, dashboard JSON, or the PoB endpoints above instead.

Orchestrator field names evolve with BeamCore releases; inspect the live responses while extending scoring logic inside [`core/validator.py`](core/validator.py).

---

## Scoring Formula

### Component Weights (must sum to 1.0)

| Component    | Weight | Description                 |
| ------------ | ------ | --------------------------- |
| Bandwidth    | 0.30   | Throughput capability       |
| Success Rate | 0.25   | Task completion reliability |
| Uptime       | 0.20   | Availability                |
| Latency      | 0.15   | Speed (inverted)            |
| Acceptance   | 0.10   | Task acceptance rate        |

### Normalization

```python
# Bandwidth: 0 Mbps = 0.0, 10 Gbps = 1.0
bandwidth_score = min(bandwidth_mbps / 10_000, 1.0)

# Latency: 0 ms = 1.0, 500+ ms = 0.0 (inverted)
latency_score = max(0, 1.0 - (latency_ms / 500))

```

### Final Weight Calculation

```
SLA Score = (
    0.30 × bandwidth_score +
    0.25 × success_rate +
    0.20 × (uptime_percent / 100) +
    0.15 × latency_score +
    0.10 × acceptance_rate
)

Final Weight = SLA Score × (1 - Penalty)

Normalized Weight = Final Weight / sum(all Final Weights)
```

---

## Scoring Options

### Option 1: Standard Scoring (Maximum Consensus)

Use BeamCore data with the standard formula. All validators using this will compute **identical weights**.

```python
from services.weight_calculator import SummaryInput, compute_weights

# Fetch from BeamCore
response = await beamcore.get("/pob/epochs/{epoch}")
summaries = [SummaryInput(**item) for item in response["summaries"]]
weight_vector = compute_weights(epoch=current_epoch, summaries=summaries)

# Set on Bittensor
subtensor.set_weights(
    netuid=NETUID,
    uids=weight_vector.uids,
    weights=weight_vector.weights,
)
```

### Option 2: Custom Scoring (Validator Autonomy)

Apply validator-specific modifiers for independent scoring.

```python
from services.weight_calculator import SummaryInput, compute_weights

# Fetch from BeamCore
response = await beamcore.get("/pob/epochs/{epoch}")
summaries = [SummaryInput(**item) for item in response["summaries"]]
weight_vector = compute_weights(epoch=current_epoch, summaries=summaries)

# Apply validator-specific policy before submission.
weights = list(weight_vector.weights)
blacklist = {"malicious_hotkey"}
for index, detail in enumerate(weight_vector.details):
    if detail.hotkey in blacklist:
        weights[index] = 0.0
```

---

## ValidatorModifiers Reference

| Modifier            | Type             | Default | Description                |
| ------------------- | ---------------- | ------- | -------------------------- |
| `weight_bandwidth`  | float            | 0.30    | Custom bandwidth weight    |
| `weight_success`    | float            | 0.25    | Custom success rate weight |
| `weight_uptime`     | float            | 0.20    | Custom uptime weight       |
| `weight_latency`    | float            | 0.15    | Custom latency weight      |
| `weight_acceptance` | float            | 0.10    | Custom acceptance weight   |
| `local_penalties`   | Dict[str, float] | {}      | Hotkey → penalty (0-1)     |
| `local_boosts`      | Dict[str, float] | {}      | Hotkey → boost (0-0.5)     |
| `blacklist`         | Set[str]         | {}      | Hotkeys to zero out        |
| `whitelist`         | Set[str]         | {}      | Hotkeys to skip penalties  |

---

## Active validation and canary fields

Bandwidth challenges and canary bytes are represented **inside proof-of-bandwidth payloads** (for example `canary_proof` fields on task results) and verified when validators call `POST /pob/{proof_id}/verify`. There is **no** `POST /validators/canary/transfer` helper in the current BeamCore v2 HTTP tree or in [`SubnetCoreClient`](clients/subnet_core_client.py).

When you need active verification, use the supported paths above or extend the client alongside new BeamCore routes—do not rely on the legacy documentation examples that referenced `/validators/canary/*`.

---

## Scoring Strategy Guide

| Strategy         | When to Use            | How                                           |
| ---------------- | ---------------------- | --------------------------------------------- |
| **Passive**      | Trust BeamCore data    | Use `compute_uid_weights()`                   |
| **Active**       | Verify claims yourself | Issue challenges, apply penalties             |
| **Conservative** | Prioritize reliability | Increase `weight_success`                     |
| **Performance**  | Prioritize speed       | Increase `weight_bandwidth`, `weight_latency` |
| **Defensive**    | Protect network        | Liberal use of `blacklist`                    |

---

## BeamCore API Endpoints

Routes are rooted at `BEAM_VALIDATOR_SUBNET_CORE_URL` with **no `/api` prefix** (matching BeamCore `core-server`).

| Endpoint | Method | Used by validator client? |
| -------- | ------ | --------------------------- |
| `/validators/orchestrators` | GET | Yes |
| `/validators/weights/{epoch}` | GET | Yes |
| `/validators/scores` | POST | Yes |
| `/validators/spot-checks` | POST | Yes |
| `/validators/weights` | POST | Yes (weight proof transcript) |
| `/validators/heartbeat` | POST | Yes |
| `/pob` | GET | Yes |
| `/pob/unverified` | GET | Yes |
| `/pob/latest-epoch` | GET | Yes |
| `/pob/{proof_id}/verify` | POST | Yes (`proof_id` is a path param; snake_case mirrors JSON keys) |
| `/validators/challenges` | POST | BeamCore exposes it, but **`SubnetCoreClient` does not call it yet** |
| `/config/uid-ranges` | GET | Bootstrap only (`main.py`); availability depends on BeamCore deployment |
| `/config/network` | GET | Optional helper in client |

---

---

## Proof Verification

Validators verify proof-of-bandwidth records fetched from BeamCore, while BeamCore owns payment verification and penalty attribution.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    PAYMENT VERIFICATION FLOW                             │
│                                                                          │
│   1. Validator fetches payment records from BeamCore API                │
│   2. For each payment, extract tx_hash (format: extrinsic:block)        │
│   3. Query Bittensor chain to verify transfer details                   │
│   4. Check: recipient matches worker, amount matches payment            │
│   5. Apply 50% SLASH for any invalid/missing tx_hash                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### tx_hash Format

Orchestrators store payment tx_hash in the format:

```
{extrinsic_hash}:{block_hash}
```

Example:

```
0xa989b4c3589bcba3574a21795ba7ffd9...:0x5c7c5471b7c70f61cb09bcc8800c7a41...
```

### Verification Checks

| Check              | What's Verified              | Failure Action |
| ------------------ | ---------------------------- | -------------- |
| tx_hash present    | Payment has on-chain proof   | 50% slash      |
| Transaction exists | Extrinsic found in block     | 50% slash      |
| Is transfer        | Call is `Balances.transfer*` | 50% slash      |
| Recipient match    | Worker received payment      | 50% slash      |
| Amount match       | Within 5% tolerance          | 50% slash      |

### Penalty Application

```python
# In validator scoring:
payment_multiplier = self.payment_penalty_multipliers.get(hotkey, 1.0)

# Normal orchestrator: payment_multiplier = 1.0 (full emissions)
# Slashed orchestrator: payment_multiplier = 0.5 (50% emissions)

final_score = sla_score × payment_multiplier
```

### Code Location

| File                          | Purpose                                    |
| ----------------------------- | ------------------------------------------ |
| `chain/__init__.py`           | Chain module exports                       |
| `core/validator.py`           | Proof verification and weight submission   |
| `beamcore_v2/doc/PROOF_OF_PAYMENT.md` | BeamCore-owned payment verification flow |

---

## Code Location

| File                                              | Purpose                                  |
| ------------------------------------------------- | ---------------------------------------- |
| `neurons/validator/services/weight_calculator.py` | Weight formula and params hash          |
| `neurons/validator/core/validator.py`             | Main validator loop                      |
| `neurons/validator/clients/subnet_core_client.py` | BeamCore API client                      |

---

## Optional: Local Database for Analytics

By default, validators are **stateless** and rely entirely on BeamCore API for all data.

However, if you want local persistence for analytics, caching, or custom tracking, you can set up your own database:

### Supported Databases

| Provider           | Connection String                                          |
| ------------------ | ---------------------------------------------------------- |
| **Local Postgres** | `postgresql+asyncpg://localhost/validator`                 |
| **Remote Postgres**| `postgresql+asyncpg://user:pass@host:5432/db?sslmode=require` |

### Configuration

Set the `DATABASE_URL` environment variable:

```bash
# Local Postgres
export DATABASE_URL="postgresql+asyncpg://localhost/validator"

# Remote Postgres (with SSL)
export DATABASE_URL="postgresql+asyncpg://user:password@host:5432/db?sslmode=require"
```

### Use Cases

| Use Case                 | Description                         |
| ------------------------ | ----------------------------------- |
| **Historical Analytics** | Track orchestrator scores over time |
| **Challenge Results**    | Persist canary transfer outcomes    |
| **Custom Penalties**     | Store local penalty decisions       |
| **Audit Trail**          | Log all weight-setting decisions    |

### Note

Local database is **optional** and does not affect consensus. All validators compute identical scores from BeamCore data regardless of local storage.
