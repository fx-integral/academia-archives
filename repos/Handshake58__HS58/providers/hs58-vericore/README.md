# HS58-Vericore

DRAIN payment gateway for the **Vericore Claim Analyzer** — verifies claims against live web evidence.

## What it does

Agents send a factual claim as plain text. Vericore searches the web for evidence and returns:
- **Entailment** — % of sources supporting the claim
- **Contradiction** — % of sources contradicting it
- **Neutral** — % of neutral coverage
- Per-source scores: sentiment, conviction, source credibility, narrative momentum

## Quick Start

```bash
cp env.example .env
# Edit .env with your keys

npm install
npm run dev
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROVIDER_PRIVATE_KEY` | Yes | — | Polygon wallet private key for DRAIN claims |
| `VERICORE_API_KEY` | Yes | — | Vericore API key |
| `VERICORE_API_URL` | No | `https://api.integration.vericore.dfusion.ai/calculate-rating/v2` | API endpoint |
| `VERICORE_TIMEOUT_MS` | No | `90000` | Request timeout (Vericore takes ~20-30s) |
| `POLYGON_RPC_URL` | No | Public RPC | Alchemy/Infura RPC for reliable claiming |
| `PORT` | No | `3000` | Server port |
| `CHAIN_ID` | No | `137` | 137 (Polygon) or 80002 (Amoy testnet) |
| `PRICE_PER_REQUEST_USDC` | No | `0.05` | Price per verification in USD |
| `CLAIM_THRESHOLD` | No | `50000` | Min USDC wei before auto-claim |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/pricing` | GET | Provider info + pricing |
| `/v1/models` | GET | Available models |
| `/v1/docs` | GET | Agent instructions |
| `/v1/chat/completions` | POST | Verify a claim (DRAIN payment required) |
| `/v1/admin/claim` | POST | Trigger payment claims |
| `/v1/admin/stats` | GET | Provider statistics |
| `/v1/admin/vouchers` | GET | Unclaimed vouchers |
| `/v1/close-channel` | POST | Cooperative channel close |
| `/health` | GET | Health check |

## Usage Example

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-DRAIN-Voucher: {"channelId":"0x...","amount":"50000","nonce":"1","signature":"0x..."}' \
  -d '{
    "model": "vericore/claim-analyzer",
    "messages": [{"role": "user", "content": "The Earth is round"}]
  }'
```

## Deploy

Configured for Railway via `railway.json`. Set env vars in Railway dashboard.
