# Constantinople — Decentralized LLM Inference

Constantinople is a decentralized inference subnet on Bittensor (SN97).
Blazing fast, always-on LLM inference with hidden state verification.
OpenAI-compatible API. Every query is audited and published as a public dataset.

## Endpoint

```
Base URL: https://api.constantinople.cloud/v1
Model: Qwen/Qwen2.5-7B-Instruct
Auth: Bearer token (API key required, prefix: cst-)
```

## Quick Start — Bittensor Wallet Auth (Recommended)

If you have a Bittensor wallet (hotkey or coldkey), authenticate directly — no email needed.
**Registered hotkeys get $100 free credits. Coldkeys get $1 per TAO.**

### Step 1: Get a signing message

```bash
curl -X POST https://api.constantinople.cloud/v1/auth/bittensor/nonce \
  -H "Content-Type: application/json" \
  -d '{"ss58_address": "5YourAddressHere..."}'
```

Returns a `message` field (format: `<ss58_address>:<timestamp>`).

### Step 2: Sign and authenticate

```python
from bittensor import Keypair
import requests

# Your wallet
kp = Keypair.create_from_seed("your-seed-hex")  # or create_from_mnemonic()

# Get signing message
resp = requests.post("https://api.constantinople.cloud/v1/auth/bittensor/nonce",
    json={"ss58_address": kp.ss58_address})
message = resp.json()["message"]

# Sign it
signature = kp.sign(message.encode()).hex()

# Authenticate
resp = requests.post("https://api.constantinople.cloud/v1/auth/bittensor",
    json={
        "ss58_address": kp.ss58_address,
        "signature": signature,
        "message": message,
    })
print(resp.json())
# Returns: api_key, balance, credits breakdown
```

### Step 3: Use the API

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.constantinople.cloud/v1",
    api_key="cst-your-key-from-step-2",
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=200,
)
print(response.choices[0].message.content)
```

## Quick Start — Email Registration

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.constantinople.cloud/v1",
    api_key="cst-your-key-here",
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=200,
)
print(response.choices[0].message.content)
```

Get an API key at https://www.constantinople.cloud/#api — free tier includes $1 on email signup.

## Authentication

Constantinople supports three auth methods:

| Method | Endpoint | Free Credits |
|--------|----------|-------------|
| **Bittensor Wallet** | `POST /v1/auth/bittensor` | $100 (hotkey) or $1/TAO (coldkey) |
| Email/Password | `POST /v1/auth/register` | $1.00 |
| Quick Start | `POST /v1/quickstart` | $1.00 |

### Bittensor Wallet Auth Flow

1. `POST /v1/auth/bittensor/nonce` — get a message to sign (`{"ss58_address": "5..."}`)
2. Sign the returned `message` with your keypair → hex signature
3. `POST /v1/auth/bittensor` — submit `ss58_address`, `signature`, `message`
4. Receive API key + auto-calculated credits

**Credit calculation:**
- Hotkey registered on ANY Bittensor subnet → **$100 free**
- Coldkey with TAO balance → **$1 per TAO** in balance
- Hotkey with TAO balance → **$100 + $1 per TAO**
- Unregistered address with no TAO → **$0** (account created, no credits)

**Signature format:**
- Message: `<ss58_address>:<unix_timestamp>`
- Timestamp must be within 5 minutes of server time
- Signature: hex-encoded result of `Keypair.sign(message.encode())`

## How It Works

```
Client → POST /v1/chat/completions (OpenAI-compatible)
       → Gateway (routes to best available miner)
       → Decentralized GPU Miners (serve inference + hidden states)
       → Audit Validator (samples requests, verifies hidden states)
       → Scoring Engine (speed × verification × consistency)
       → On-chain weight setting via commit-reveal
```

Miners prove they're running the real model by returning hidden state vectors
that match the validator's reference within cosine similarity > 0.995.

## Available Endpoints

### Auth
- `POST /v1/auth/bittensor/nonce` — Get signing message for wallet auth
- `POST /v1/auth/bittensor` — Authenticate with Bittensor wallet (auto-creates account)
- `POST /v1/auth/register` — Email/password registration
- `POST /v1/auth/login` — Email/password login
- `POST /v1/quickstart` — Register + get ready-to-use examples in one call

### Inference
- `POST /v1/chat/completions` — Chat completions (OpenAI-compatible)
- `POST /v1/completions` — Text completions
- `POST /v1/embeddings` — Text embeddings

### Account
- `GET /v1/user/balance` — Check credit balance
- `GET /v1/user/usage` — Usage analytics
- `GET /v1/user/transactions` — Transaction history
- `POST /v1/keys/create` — Create additional API keys
- `GET /v1/keys` — List API keys
- `DELETE /v1/keys/{key_id}` — Revoke an API key

### Billing
- `GET /v1/billing/tao-deposit` — Get TAO deposit address
- `POST /v1/billing/topup` — Top up credits (crypto or Stripe)
- `GET /v1/billing/tao-price` — Current TAO/USD price

### Info
- `GET /v1/models` — List available models
- `GET /v1/pricing` — Current pricing
- `GET /health` — API health status

## Pricing

- Input: $0.50 per 1M tokens
- Output: $1.50 per 1M tokens
- Email signup: $1.00 free
- Bittensor hotkey: $100 free
- Bittensor coldkey: $1 per TAO

## Properties

- **Model**: Qwen/Qwen2.5-7B-Instruct (7B parameters)
- **Network**: Bittensor Subnet 97
- **Throughput**: Scales with miners — no single point of failure
- **Verification**: Hidden state challenge protocol (cosine similarity verification)
- **Compatibility**: OpenAI chat completions API
- **Streaming**: Supported
- **Dataset**: All queries audited and published to Cloudflare R2

## Machine-Readable

```json
{
  "name": "Constantinople",
  "network": "bittensor",
  "subnet": 97,
  "model": "Qwen/Qwen2.5-7B-Instruct",
  "api_base": "https://api.constantinople.cloud/v1",
  "auth": ["bearer", "bittensor_wallet"],
  "auth_prefix": "cst-",
  "bittensor_auth": {
    "nonce_endpoint": "/v1/auth/bittensor/nonce",
    "auth_endpoint": "/v1/auth/bittensor",
    "message_format": "<ss58_address>:<unix_timestamp>",
    "signature_type": "sr25519",
    "credits": {
      "registered_hotkey": 100.0,
      "coldkey_per_tao": 1.0
    }
  },
  "endpoints": {
    "chat": "/v1/chat/completions",
    "completions": "/v1/completions",
    "models": "/v1/models",
    "balance": "/v1/user/balance",
    "pricing": "/v1/pricing"
  },
  "capabilities": ["stream", "chat", "completions", "embeddings"],
  "pricing": {
    "input_per_1m": 0.50,
    "output_per_1m": 1.50,
    "currency": "USD"
  }
}
```
