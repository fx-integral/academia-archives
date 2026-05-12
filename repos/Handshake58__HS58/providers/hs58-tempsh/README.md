# HS58-TempSh Provider

DRAIN payment gateway for [temp.sh](https://temp.sh/) temporary file hosting.  
AI agents pay per upload via USDC micropayments on Polygon. Files are proxied to temp.sh (free service) and expire after **3 days**.

**Business model:** temp.sh is completely free → every payment is profit.

---

## How It Works

1. Agent opens a DRAIN channel with USDC deposit on Polygon
2. Agent POSTs a file with a signed `X-DRAIN-Voucher` header
3. Provider validates the voucher on-chain
4. File is uploaded to `https://temp.sh/upload`
5. Provider returns the public temp.sh URL
6. Provider periodically claims accumulated USDC from the smart contract

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/pricing` | Pricing info and limits |
| `GET` | `/v1/models` | Available models |
| `GET` | `/v1/docs` | Agent instructions |
| `POST` | `/v1/files/upload` | Native multipart file upload |
| `POST` | `/v1/chat/completions` | Chat-compatible wrapper (base64) |
| `POST` | `/v1/close-channel` | Cooperative channel close |
| `POST` | `/v1/admin/claim` | Trigger payment claim |
| `GET` | `/v1/admin/stats` | Provider stats |
| `GET` | `/health` | Health check |

---

## Upload: Native API

```bash
curl -X POST https://your-provider.railway.app/v1/files/upload \
  -H "X-DRAIN-Voucher: <signed-voucher-json>" \
  -F "file=@report.pdf"
```

Response:
```json
{
  "url": "https://temp.sh/XXXX/report.pdf",
  "filename": "report.pdf",
  "sizeBytes": 102400,
  "expiresIn": "3 days"
}
```

---

## Upload: Chat-Compatible API

```bash
curl -X POST https://your-provider.railway.app/v1/chat/completions \
  -H "X-DRAIN-Voucher: <signed-voucher-json>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tempsh/upload",
    "messages": [{
      "role": "user",
      "content": "{\"filename\": \"hello.txt\", \"content\": \"SGVsbG8gV29ybGQ=\", \"mimeType\": \"text/plain\"}"
    }]
  }'
```

---

## Pricing Modes

### Flat Rate (default)
Every upload costs the same regardless of file size.  
Default: `$0.005` × 1.5 markup = **$0.0075 USDC per upload**.

### Per-MB
Charged by file size (ceil to next MB, min 1 MB).  
Default: `$0.002` × 1.5 markup = **$0.003 USDC per MB**.

Set `PRICING_MODE=per-mb` to switch.

---

## Setup

```bash
cp env.example .env
# Fill in PROVIDER_PRIVATE_KEY and optionally POLYGON_RPC_URL
npm install
npm run dev
```

## Deploy to Railway

```bash
railway up
```

Set environment variables in the Railway dashboard. The `railway.json` handles build and start commands automatically.

---

## Limits

- **Max file size**: 100 MB (configurable, temp.sh supports up to 4 GB)
- **File TTL**: 3 days (temp.sh hard limit, cannot be extended)
- **Rate limit**: 20 uploads/min per payment channel (configurable)
- **MIME filtering**: Allow/deny specific file types via `ALLOWED_MIME_TYPES`
