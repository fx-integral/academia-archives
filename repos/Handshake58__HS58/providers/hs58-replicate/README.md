# HS58-Replicate

DRAIN payment gateway for **Replicate.com** — image, video, audio, LLM, 3D and more via 300+ auto-curated models.

## What it does

A universal gateway to Replicate's model ecosystem. Models are automatically synced from Replicate collections and assigned to pricing tiers. Agents discover models, get input schemas, and run predictions — all through standard DRAIN payment channels.

### Supported categories

| Category | Examples | Price tier |
|----------|----------|-----------|
| Image Generation | FLUX, SDXL, Ideogram | $0.03/run |
| Video Generation | Wan, Veo, Ray | $0.30/run |
| Language Models | Llama 4, DeepSeek, Claude | $0.01/run |
| Audio | Whisper, TTS, Music Gen | $0.05/run |
| Image Editing | Upscaling, Background Removal | $0.03/run |
| Video Editing | Enhancement, Lipsync | $0.15/run |
| 3D | 3D Model Generation | $0.15/run |
| Utility | OCR, Classification, Embeddings | $0.03/run |

*Prices shown before markup. Default markup is 50%.*

## Quick Start

```bash
cp env.example .env
# Edit .env with your keys

npm install
npm run dev
```

On startup, the provider syncs models from Replicate collections. This takes ~30 seconds.

## How Agents Use It

```
1. GET /v1/collections              → Browse categories
2. GET /v1/models?collection=...    → List models in a category
3. GET /v1/models/{owner}/{name}    → Get input/output schema
4. POST /v1/chat/completions        → Run prediction (DRAIN payment)
```

### Simple request (prompt-based)

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-DRAIN-Voucher: {"channelId":"0x...","amount":"45000","nonce":"1","signature":"0x..."}' \
  -d '{
    "model": "replicate/black-forest-labs/flux-dev",
    "messages": [{"role": "user", "content": "A cat in space, digital art"}]
  }'
```

### Complex request (JSON input)

```bash
curl -X POST http://localhost:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-DRAIN-Voucher: ...' \
  -d '{
    "model": "replicate/wavespeedai/wan-2.1-i2v-480p",
    "messages": [{"role": "user", "content": "{\"image\": \"https://example.com/photo.jpg\", \"prompt\": \"make it move\"}"}]
  }'
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROVIDER_PRIVATE_KEY` | Yes | — | Polygon wallet private key |
| `REPLICATE_API_TOKEN` | Yes | — | Replicate API token |
| `MARKUP_PERCENT` | No | `50` | Markup on tier prices |
| `SYNC_INTERVAL_HOURS` | No | `24` | Hours between collection re-syncs |
| `SYNC_COLLECTIONS` | No | 13 defaults | Comma-separated collection slugs |
| `MAX_PREDICTION_TIMEOUT_MS` | No | `600000` | Max wait for predictions (10min) |
| `POLYGON_RPC_URL` | No | Public RPC | Reliable RPC for claiming |
| `PORT` | No | `3000` | Server port |
| `CHAIN_ID` | No | `137` | 137 (Polygon) or 80002 (Amoy) |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/pricing` | GET | Pricing tiers and provider info |
| `/v1/models` | GET | List models (`?collection=`, `?search=`, `?limit=`, `?offset=`) |
| `/v1/models/:owner/:name` | GET | Model detail with input/output schema |
| `/v1/collections` | GET | Available collections with model counts |
| `/v1/docs` | GET | Agent instructions |
| `/v1/chat/completions` | POST | Run prediction (DRAIN payment required) |
| `/v1/admin/claim` | POST | Trigger payment claims |
| `/v1/admin/stats` | GET | Provider statistics |
| `/v1/admin/vouchers` | GET | Unclaimed vouchers |
| `/v1/admin/sync` | POST | Force registry re-sync |
| `/v1/close-channel` | POST | Cooperative channel close |
| `/health` | GET | Health check |

## Auto-Curation

The model registry automatically syncs from these Replicate collections on startup and every 6 hours:

`official`, `text-to-image`, `image-to-video`, `text-to-video`, `language-models`, `speech-to-text`, `text-to-speech`, `super-resolution`, `image-editing`, `vision-models`, `3d-models`, `wan-video`, `flux`

New models added by Replicate to these collections appear automatically at the next daily sync.

## Deploy

Configured for Railway via `railway.json`. Set env vars in Railway dashboard. Mount a volume at `/app/data` to persist the model registry and vouchers.
