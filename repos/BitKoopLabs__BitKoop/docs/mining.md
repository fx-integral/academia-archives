## BitKoop Mining Guide

This short guide explains what a miner needs to do to participate in the BitKoop subnet.

---

### 1) Register your hotkey on the subnet

Register your hotkey on the subnet using the Bittensor CLI:

```sh
btcli subnet register --netuid 16
```

---

### 2) Miner tasks

- Submit discount codes
  - Up to 8 active codes per website per miner
  - Each website has a limited number of slots for active coupons (typically 15 slots)
  - Slots are shared across all miners - first come, first served
  - Keep submissions fresh and genuine; expired or non-working codes will be marked INVALID by validators

- Maintain your codes
  - Recheck previously INVALID codes after cooldown if you believe they became valid again
  - Delete codes that are no longer valid to keep the dataset clean

- Monitor performance
  - Track your rank and scores over time; recent, working codes improve your normalized weight

### Interface: BitKoop Miner Server

- Repository: [BitKoop-Miner](https://github.com/BitKoopLabs/BitKoop-Miner)
- Deploy the miner server on a VPS for continuous operation
- The server handles coupon submission, validation, and TLSN proof generation
- Configure with your Bittensor wallet for authenticated operations

### CLI Interface: BitKoop Miner CLI

- Repository: [BitKoop-CLI](https://github.com/BitKoop-com/BitKoop-CLI)
- Install and follow its usage guide for commands to submit, recheck, delete codes, list sites, and check ranks
- The CLI uses your Bittensor wallet configuration for authenticated operations


