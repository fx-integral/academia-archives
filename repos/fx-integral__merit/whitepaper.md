# Merit Subnet — Whitepaper

---

## 1. Believe

**Merit** is a Bittensor subnet designed to reward miners for their **active participation across other Bittensor subnets**.

Validators in Merit evaluate **registered hotkeys** based on their contribution elsewhere in the Bittensor ecosystem, assigning dynamic rewards based on a calculated **Bittensor Miner Participation Score (BMPS)**.

Merit encourages real work, broad participation, and sustained online presence.

---

## 2. Registration

Miners must register their **hotkey** directly to the Merit subnet (`netuid 73`).

- Registration happens on-chain following Bittensor standards.
- Only **hotkeys registered to Merit** will be evaluated and scored.

---

## 3. Incentive Mechanism (Finalized)

Merit's validator scoring process operates as follows:

### Step 1: Global Refresh Each Epoch

- Validators call `subtensor.get_all_metagraphs_info()` once per epoch.
- Only active subnets are considered.
- Netuid 0 (root) and Netuid 73 (Merit) are excluded.

---

### Step 2: 1:1 Hotkey Lookup

For each **hotkey registered on Merit**:

- Validator searches for the **same hotkey** across **all other active subnets**.
- If found, collects the hotkey's incentive from that subnet.

---

### Step 3: Incentive Averaging

- Validators **sum all incentives found** across all other subnets.
- **Average incentive** is calculated by:

```text
average_incentive = (sum of found incentives) / (total number of active subnets - 2)
```

Where:

- Active subnets exclude netuid 0 and 73.
- Missing entries are treated as zero.

✅ This design **rewards broad multi-subnet participation**.

---

### Step 4: BMPS Score Calculation

The **Bittensor Miner Participation Score (BMPS)** is:

```text
bmps = average_incentive × 100,000
```

Then adjusted for liveness:

| Event | Effect on BMPS    |
|-------|-------------------|
| Failed ping (after retries) | `bmps == 0.0` |

✅ **Ping** acts as a **small fine-tuning adjustment**,  
✅ **Incentives** remain the **dominant factor**.

---

### Step 5: Normalization and Submission

- All BMPS scores are normalized across registered miners.
- Weights are submitted via `set_weights()` to the Bittensor chain.

---

## 4. Security and Verification

- **Public IPv4 Address Validation** ensures only reachable miners are scored.
- **TOTP-Secured Pings** verify real miner presence using hotkey-seeded secrets.
- **Type-Checked Responses** protect against invalid or garbage returns.
- **Background Health Checks** record miner uptime over time.

---

## 5. Anti-Gaming Measures

| Threat | Mitigation |
|--------|------------|
| Registering a single subnet to maximize reward | ✅ Averaging across all subnets |
| Faking responses | ✅ TOTP cryptographic verification |
| Hosting on invalid IPs | ✅ Public IPv4 validation |
| Ghost miners registering but never serving | ✅ Live ping penalties |

---

## 6. Technical Parameters

| Parameter | Value                |
|-----------|----------------------|
| Subnet UID (Merit) | 73                   |
| Epoch Tempo | 360 blocks (~1 hour) |
| Ping Timeout | 10 seconds           |
| Ping Retries | 2                    |
| Ping Failure Penalty | bmps == 0.0          |
| Max Validators | 64                   |
| Max Stored Epoch Files | 48                   |
| Default Network | finney               |

---

## 7. Future Extensions

- **Merit Dashboard** to track miner performance live.
- **Subnet Popularity and Complexity Index** for scaling BMPS.
- **Dynamic Liveness Models** based on uptime history.

---

# 📋 Summary

Merit creates a decentralized, incentive-driven system where miners are rewarded fairly based on their **broad, real-world contribution** to the Bittensor ecosystem.

✅ Validators refresh incentives dynamically.  
✅ Miners are evaluated per hotkey, per subnet.  
✅ Uptime and participation both matter — but contribution comes first.

Merit rewards **real work**, not empty registrations.

---
