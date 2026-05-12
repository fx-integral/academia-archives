# Merit Subnet — Validator Setup Guide

---

## Overview

This guide explains how to deploy a **Merit subnet validator** to participate in evaluating miners based on their active participation across the Bittensor network.

Merit validators:

- Score miners **per-hotkey** based on external subnet incentives.
- Perform **dynamic global incentive refresh** every epoch.
- Conduct **TOTP-secured pings** to verify miner liveness.
- Submit **normalized weights** dynamically to the Bittensor chain.

---

## Requirements

- Linux server or machine (Ubuntu 20.04+ recommended).
- Python 3.10+ with virtualenv support.
- Stable network connection.
- Open ports for outbound traffic (pinging miners).
- Accurate system clock (important for TOTP verification).

---

## 1. Install Dependencies

```bash
sudo apt -y install python3-venv python3-pip python-is-python3
sudo apt -y install ntpsec
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/fx-integral/merit.git
cd merit
```

---

## 3. Set Up a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install uv
uv pip install -r requirements.txt
```

---

## 4. Run the Validator

```bash
python -m merit.scripts.run_validator \
    --subtensor.network finney \
    --wallet.name {your_wallet_name} \
    --wallet.hotkey {your_hotkey_name} \
    --netuid 73 \
    --logging.debug
```

---

## 5. Optional Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--ping_frequency` | Seconds between background pings | 120 |

Example:

```bash
python -m merit.scripts.run_validator --ping_frequency 120
```

---

## 6. Validator Behavior

| Feature | Description                                                                     |
|---------|---------------------------------------------------------------------------------|
| **Dynamic Global Refresh** | Fetches full network miner info every epoch.                                    |
| **Hotkey-Specific Scoring** | Each registered hotkey is scored individually (no coldkey aggregation).         |
| **Incentive Averaging** | Rewards are averaged across **all active subnets** (excluding netuid 0 and 73). |
| **BMPS Calculation** | `bmps = (sum incentives / (active_subnets - 2)) × 100,000`                      |
| **Ping Adjustments** | -100% for failure                                                               |
| **Weight Submission** | Normalized weights submitted after each epoch.                                  |

---

## 7. Troubleshooting

| Issue | Resolution |
|-------|------------|
| Time synchronization errors | Install and run `ntpsec` to correct system clock. |
| Validator crash during RPC calls | Validators auto-retry connection failures. |
| No miners found warning | Happens if all hotkeys are invalid, banned, or unreachable. |

---

## 8. Useful Commands

Deactivate virtual environment:

```bash
deactivate
```

Activate virtual environment:

```bash
source venv/bin/activate
```

Pull repository updates:

```bash
git pull origin main
```

---

## 9. Important Notes

- Validators must have **validator permit** granted on the Merit subnet.
- Only hotkeys registered on Merit are scored — not external ones.
- Miners must be serving valid public IPv4 axons to avoid being skipped.

---

## License

This project is licensed under the MIT License.  
See [LICENSE](../LICENSE) for details.

---
