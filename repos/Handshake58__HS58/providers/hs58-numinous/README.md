# HS58-Numinous

DRAIN payment gateway for **Numinous Forecasting** — probabilistic predictions from the world's best forecasting agents.

## What it does

Agents send a question about a future event. Numinous routes it to top forecasting agents on its network and returns a probability estimate between 0 and 1 reflecting the likelihood that the event resolves positively.

Supports two input modes:
- **Query mode** — natural language question (e.g. "Will Bitcoin exceed $150k before Q1 2026?")
- **Structured mode** — JSON with `title`, `description`, `cutoff`, and optional `topics` for precise forecasts

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
| `NUMINOUS_API_KEY` | Yes | — | Numinous API key |
| `NUMINOUS_API_URL` | No | `https://api.numinouslabs.io` | API base URL |
| `NUMINOUS_POLL_INTERVAL_MS` | No | `5000` | Polling interval between status checks |
| `NUMINOUS_POLL_TIMEOUT_MS` | No | `240000` | Max wait time for forecast completion (4min) |
| `POLYGON_RPC_URL` | No | Public RPC | Alchemy/Infura RPC for reliable claiming |
| `PORT` | No | `3000` | Server port |
| `CHAIN_ID` | No | `137` | 137 (Polygon) or 80002 (Amoy testnet) |
| `PRICE_PER_REQUEST_USDC` | No | `0.10` | Price per forecast in USD |
| `CLAIM_THRESHOLD` | No | `50000` | Min USDC wei before auto-claim |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/pricing` | GET | Provider info + pricing |
| `/v1/models` | GET | Available models |
| `/v1/docs` | GET | Agent instructions |
| `/v1/chat/completions` | POST | Request a forecast (DRAIN payment required) |
| `/v1/admin/claim` | POST | Trigger payment claims |
| `/v1/admin/stats` | GET | Provider statistics |
| `/v1/admin/vouchers` | GET | Unclaimed vouchers |
| `/v1/close-channel` | POST | Cooperative channel close |
| `/health` | GET | Health check |

## Usage Example

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-DRAIN-Voucher: {"channelId":"0x...","amount":"100000","nonce":"1","signature":"0x..."}' \
  -d '{
    "model": "numinous/forecaster",
    "messages": [{"role": "user", "content": "Will Bitcoin exceed $150,000 before March 31, 2026?"}]
  }'
```

## Response Time

Forecasts typically complete in 30–120 seconds. Maximum wait is ~4 minutes. The provider handles polling internally and returns the result once ready.

## Deploy

Configured for Railway via `railway.json`. Set env vars in Railway dashboard.
