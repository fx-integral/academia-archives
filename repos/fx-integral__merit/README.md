# Merit Subnet (Bittensor NetUID 73)

---

## Overview

Merit is a Bittensor subnet that rewards miners for their **active participation across other Bittensor subnets**.

Validators evaluate **registered hotkeys** based on their cross-subnet activity and uptime, assigning dynamic weights according to a calculated **Bittensor Miner Participation Score (BMPS)**.

Merit is designed to promote real work, broad contribution, and fair validation.

---

## Key Features

- ✅ **Hotkey-Based Rewards**: Each hotkey registered on Merit is scored individually.
- ✅ **Cross-Subnet Incentive Averaging**: Miners must be active across many subnets to maximize rewards.
- ✅ **Dynamic Global Refresh**: Validator refreshes all miner incentives every epoch.
- ✅ **TOTP-Secured Liveness Checks**: Pings confirm miners are live and serving.
- ✅ **Fair Scoring System**: Ping rewards are minor compared to true network participation.
- ✅ **Background Health Monitoring**: Optional miner uptime history tracking.

---

## Incentive Mechanism

| Step | Description                                                              |
|------|--------------------------------------------------------------------------|
| 1 | Validator fetches full Bittensor network info per epoch.                 |
| 2 | For each Merit hotkey, search all active subnets (excluding root/merit). |
| 3 | Sum found incentives and divide by the total active subnets - 2.         |
| 4 | Compute: `bmps = average_incentive × 100,000`.                           |
| 5 | Apply ping adjustments: bmps == 0.0 for failure.                         |
| 6 | Normalize and submit weights each epoch.                                 |

---

## Getting Started

### 1. Install Dependencies

```bash
sudo apt -y install python3-venv python3-pip python-is-python3
sudo apt -y install ntpsec
```

### 2. Clone and Set Up Environment

```bash
git clone https://github.com/fx-integral/merit.git
cd merit
python3 -m venv venv
source venv/bin/activate
pip install uv
uv pip install -r requirements.txt
```

---

## Running a Miner

```bash
python -m merit.scripts.run_miner \
    --subtensor.network finney \
    --wallet.name {your_wallet_name} \
    --wallet.hotkey {your_hotkey_name} \
    --netuid 73 \
    --axon.port {port_number} \
    --logging.debug
```

---

## Running a Validator

```bash
python -m merit.scripts.run_validator \
    --subtensor.network finney \
    --wallet.name {your_wallet_name} \
    --wallet.hotkey {your_hotkey_name} \
    --netuid 73 \
    --logging.debug
```

Optional Arguments:

| Argument | Description | Default |
|----------|-------------|---------|
| `--ping_frequency` | Seconds between background pings | 120 |

---

## Important Notes

- **Hotkey-Specific Scoring**: Coldkeys are not aggregated — only hotkeys matter.
- **Dynamic Subnet Participation**: The more subnets a miner actively participates in, the higher the score.
- **Liveness Matters**: Online miners gain slight bonus; offline miners are lightly penalized.
- **No Validator Restart Needed**: Incentives refresh automatically each epoch.

---

## Documentation

- 📄 [Whitepaper](whitepaper.md)
- 📄 [Validator Setup Guide](docs/validator_setup.md)
- 📄 [Miner Setup Guide](docs/miner_setup.md)
- 📄 [Roadmap](roadmap.md)

---

## License

This project is licensed under the MIT License.  
See [LICENSE](LICENSE) for details.

---
