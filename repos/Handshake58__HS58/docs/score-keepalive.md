# Score Keepalive — How to Maintain Your Miner Score

## The Problem

Your `tao_score` on the Handshake58 marketplace shows `0.0000` because the Bittensor validator scores miners based on real **DRAIN ChannelClaimed events** on Polygon (7-day rolling window). No payments = no claims = no score.

## The Solution

Run a self-test payment to your own provider. This generates a real on-chain `ChannelClaimed` event that the validator picks up.

### What happens:

```
Your Agent Wallet → opens DRAIN channel ($0.10 USDC)
                  → sends AI request with $0.01 voucher
                  → your Provider claims the voucher on-chain
                  → Validator scans ChannelClaimed event
                  → Your tao_score increases
```

### Cost per test: ~$0.13

| Item | Cost |
|------|------|
| DRAIN channel deposit | $0.10 USDC |
| Voucher (AI request) | $0.01 USDC |
| Gas (channel open + claim) | ~$0.02 MATIC |
| **Total** | **~$0.13** |

> The $0.10 deposit minus the $0.01 voucher = $0.09 remains in the channel and can be withdrawn after expiry (24h).

---

## Step-by-Step

### 1. Create an Agent Wallet

You need a separate Polygon wallet to act as the "agent" (customer). Don't use your provider wallet.

```bash
# Using cast (Foundry)
cast wallet new

# Or using Node.js
node -e "const w = require('ethers').Wallet.createRandom(); console.log('Address:', w.address, '\nKey:', w.privateKey)"
```

Fund it with:
- **~$1 USDC** on Polygon (enough for ~7 tests)
- **~0.1 MATIC** for gas

### 2. Install dependencies

```bash
cd HS58/scripts
npm install ethers
```

### 3. Run the test payment

```bash
# Test your specific provider
node test-payment.mjs --provider "your-provider-name"

# Or test all providers (marketplace-wide)
node test-payment.mjs

# Dry run (just list providers, no payments)
node test-payment.mjs --dry-run
```

### Environment Variables

```bash
# Required: Your agent wallet private key
AGENT_PRIVATE_KEY=0x...

# Optional: Custom RPC (recommended)
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# Optional: Custom marketplace URL
MARKETPLACE_URL=https://handshake58.com
```

### 4. Verify

After the script runs:
1. Your provider auto-claims the voucher (within 10 minutes)
2. Check your provider on [handshake58.com/directory](https://handshake58.com/directory)
3. `tao_score` should update after the next validator scoring cycle

---

## Recommended Schedule

Run once per week to stay in the 7-day rolling window.

| Frequency | Monthly Cost | Score Impact |
|-----------|-------------|--------------|
| Weekly | ~$0.52 | Maintains baseline score |
| Daily | ~$3.90 | Higher score visibility |
| On-demand | Varies | When you need a score boost |

> **Tip:** The validator scores relative to the top provider. If you're the only active miner, even one claim per week gives you a significant score.

---

## Automation (Optional)

Set up a cron job or GitHub Action to run weekly:

```bash
# crontab -e (Linux/Mac)
0 12 * * 1 cd /path/to/HS58/scripts && AGENT_PRIVATE_KEY=0x... node test-payment.mjs --provider "my-provider"
```

Or use Railway's cron service to run the script on a schedule.

---

## FAQ

**Q: Is this gaming the system?**
A: No. The payment is real — you deposit real USDC, your provider delivers real AI inference, and the claim is a real on-chain transaction. Self-testing is expected and encouraged to prove your provider works.

**Q: Can I use the same wallet for agent and provider?**
A: No. The DRAIN contract requires different consumer and provider addresses. Use a separate wallet for the agent role.

**Q: What if the claim fails?**
A: The provider auto-claims within 10 minutes. If it fails, check your provider logs. Common issues: missing `POLYGON_RPC_URL` (use Alchemy), or the provider service is down.

**Q: Does the unused deposit ($0.09) come back?**
A: Yes. After the channel expires (24h), the remaining balance can be withdrawn by the agent wallet. Or you can open more channels and use the deposit for multiple requests.
