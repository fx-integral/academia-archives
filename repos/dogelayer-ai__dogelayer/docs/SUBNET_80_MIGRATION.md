# Subnet Migration: 109 -> 80

This document describes what **miners** and **validators** need to change to switch from DogeLayer **Subnet 109** to **Subnet 80**.

## Summary

- **Old subnet (netuid)**: `109`
- **New subnet (netuid)**: `80`
- **What changes**: Bittensor CLI commands (`--netuid`) and any `NETUID` environment variable.
- **What does not change**: Your wallet keys (coldkey/hotkey) and your mining hardware configuration (stratum URL / username) unless explicitly stated by the subnet operator.

You can switch between the old and new subnet from the entry selector on:

- https://dogelayer.ai/en

---

## Miners: What to Change

### 1) Register to the new subnet

If your hotkey was previously registered on subnet 109, you must register it on subnet 80.

```bash
btcli subnet register \
  --netuid 80 \
  --wallet.name YOUR_WALLET \
  --wallet.hotkey YOUR_HOTKEY \
  --subtensor.network finney
```

### 2) Update your mining endpoint (Stratum URL)

Update your miner's pool/endpoint from:

- `stratum+tcp://stratum.dogelayer.ai:3331`

to:

- Primary: `stratum+tcp://sn80-stratum.dogelayer.ai:3331`
- Backup: `stratum+tcp://stratum.dogelayer.ai:3331`

### 3) Update any commands that reference netuid

Examples:

```bash
# Check registration / stake on subnet 80
btcli wallet overview \
  --wallet.name YOUR_WALLET \
  --netuid 80 \
  --subtensor.network finney

# Inspect subnet state
btcli subnet metagraph \
  --netuid 80 \
  --subtensor.network finney
```
---

## Validators: What to Change

### 1) Register to the new subnet

```bash
btcli subnet register \
  --netuid 80 \
  --wallet.name YOUR_WALLET \
  --wallet.hotkey YOUR_HOTKEY \
  --subtensor.network finney
```

### 2) Stake (if required)

Validators must have sufficient stake to set weights.

```bash
btcli stake add \
  --wallet.name YOUR_WALLET \
  --wallet.hotkey YOUR_HOTKEY \
  --amount 10.0 \
  --subtensor.network finney

btcli wallet overview \
  --wallet.name YOUR_WALLET \
  --netuid 80 \
  --subtensor.network finney
```

### 3) Update validator environment/config

If you run the validator with a `.env` file, update:

```env
NETUID=80
SUBTENSOR_NETWORK=finney
BT_WALLET_NAME=your_wallet_name
BT_WALLET_HOTKEY=your_hotkey_name
SUBNET_PROXY_API_URL="http://dogelayer-205dd0511d5781e4.elb.ap-southeast-1.amazonaws.com:8889"
```

If your validator uses the subnet proxy API, update `SUBNET_PROXY_API_URL` to the new subnet 80 endpoint shown above.

---

## Verification Checklist

- **Miner**:
  - Wallet hotkey is registered on `--netuid 80`.
  - You can see your hotkey in `btcli subnet metagraph --netuid 80`.

- **Validator**:
  - Validator hotkey is registered on `--netuid 80`.
  - Validator has sufficient stake.
  - Validator is successfully setting weights on subnet 80.

---

## Notes

- If you were previously running anything with `NETUID=109`, it will continue to target subnet 109 until you update it.
- If you need to support *both* subnets temporarily, run separate processes/configs with different `NETUID` values.
