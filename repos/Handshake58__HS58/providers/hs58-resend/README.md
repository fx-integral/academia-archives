# HS58-Resend Provider

DRAIN payment gateway for the [Resend](https://resend.com) email API. Enables AI agents to send transactional emails with crypto micropayments.

## Features

- Send emails via DRAIN micropayments (no API key needed for consumers)
- Flat-rate per-email pricing in USDC
- OpenAI chat completions wrapper for agent compatibility
- Direct `/v1/emails/send` endpoint for native integration

## Quick Start

1. Get a Resend API key at [resend.com](https://resend.com)
2. Verify your domain in the Resend dashboard
3. Set environment variables (see below)
4. Deploy

## Environment Variables

```bash
# Required
RESEND_API_KEY=re_...
RESEND_DEFAULT_FROM=noreply@yourdomain.com
PROVIDER_PRIVATE_KEY=0x...

# Recommended
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# Optional
RESEND_ALLOWED_DOMAINS=yourdomain.com
PRICE_PER_EMAIL=0.003
CHAIN_ID=137
CLAIM_THRESHOLD=1000000
MARKUP_PERCENT=50
PROVIDER_NAME=HS58-Resend
PORT=3000
```

## API Endpoints

### `POST /v1/emails/send` — Send email (direct)

Requires `X-DRAIN-Voucher` header.

```json
{
  "from": "noreply@yourdomain.com",
  "to": ["user@example.com"],
  "subject": "Hello",
  "html": "<p>Hello World</p>"
}
```

### `POST /v1/chat/completions` — Send email (chat wrapper)

For agent compatibility. Send email params as JSON in the user message.

```json
{
  "model": "resend/send-email",
  "messages": [
    {
      "role": "user",
      "content": "{\"to\": [\"user@example.com\"], \"subject\": \"Hello\", \"html\": \"<p>Hi!</p>\"}"
    }
  ]
}
```

### `GET /v1/pricing` — View pricing
### `GET /v1/models` — List available models
### `GET /v1/docs` — Agent instructions
### `GET /health` — Health check

## Pricing

Default: **$0.003 per email** (+ markup). Configurable via `PRICE_PER_EMAIL`.

## Deployment

1. Deploy to Railway with root directory `/providers/hs58-resend`
2. Set environment variables
3. Register in Handshake58 Marketplace
