## BitKoop Validator Setup Guide

This guide will walk you through setting up a BitKoop validator node.

Note: For subnet registration and system overview, see the main README.

---

## 🟢 Quick Start: Remote Docker Compose Setup

1. Create a new directory for the validator and enter it:

   ```sh
   mkdir BitKoop
   cd BitKoop
   ```

2. Download the latest `docker-compose.yml` from the official repository:

   ```sh
   curl -L -o docker-compose.yml https://raw.githubusercontent.com/BitKoopLabs/BitKoop/main/docker-compose.yml
   ```

3. Start the validator (and watchtower) in the background:

   ```sh
   docker compose up -d
   ```

   ⚠️ Warning: By default, the validator will use the wallet name `default` and hotkey `default`. It is strongly recommended to set your own wallet name and hotkey for security and proper operation. See Wallet Customization below for instructions.

   Tip: You can customize the port by setting the `PORT` environment variable, either in your `.env` file or directly when starting Docker Compose:

   ```sh
   PORT=9000 docker compose up -d
   ```

   Or edit the `PORT` value in your `.env` file. This is the recommended way to change the port (default is `8000`).

4. Post your external IP and port to the chain (required for network participation):

   ```sh
   docker compose exec bitkoop-validator fiber-post-ip \
     --netuid <NETUID> \
     --external_ip <YOUR_IP> \
     --external_port <YOUR_PORT>
   ```

   - See the Fiber Post IP to Chain documentation for more details and command options: `https://fiber.sn19.ai/how-it-works/post-ip-to-chain/`.
   - Make sure the port you specify is open and forwarded to your machine if behind NAT/firewall.

5. Check if it's running:

   Use the following command to check a simple info endpoint from your VPS (replace `$PORT` with your configured port if different):

   ```sh
   curl http://localhost:${PORT:-8000}/info/sync
   ```

   You should see a JSON response containing fields like `progress` and `last_result`.

---

## 🖥️ Hardware Requirements

- **Minimum**: 2 vCPU, 2–4 GB RAM

These values account for asyncio-based concurrency and the Fiber framework overhead. No browser automation is used.

---

## 🛑 Alternative: Running Locally (Not Recommended)

- The recommended way to run the validator is with Docker Compose.
- Running locally is only for advanced users who need to run outside Docker.
- There is no autoupdate support when running locally.

If you still want to run locally:

1. Clone the repository and set up your environment:

   ```sh
   git clone https://github.com/BitKoopLabs/BitKoop.git
   cd BitKoop
   python3 -m venv venv
   source venv/bin/activate
   pip install .
   ```

2. Create your environment file:

   ```sh
   cp env.example .env
   # then edit .env to set WALLET_NAME, WALLET_HOTKEY, and other variables
   ```

3. Run database migrations and start the API:

   ```sh
   alembic upgrade head
   uvicorn subnet_validator.main:app --host 0.0.0.0 --port ${PORT:-8000}
   ```

---

## ⚙️ Wallet Customization

You must set your Bittensor wallet name and hotkey for the validator to function correctly. There are two recommended ways to do this:

### 1. Using a `.env` File (Recommended)

1. Copy the example environment file and rename it:

   ```sh
   cp env.example .env
   ```

2. Open `.env` in your editor and fill in your wallet details:

   ```env
   WALLET_NAME=my_wallet
   WALLET_HOTKEY=my_hotkey
   # You can add other variables as needed
   ```

3. Start Docker Compose as usual:

   ```sh
   docker compose up -d
   ```

   The validator will automatically use the values from your `.env` file.

See the `env.example` file for all available variables you can set.

### 2. Overriding via Command Line

You can also override these variables directly when starting Docker Compose:

```sh
WALLET_NAME=my_wallet WALLET_HOTKEY=my_hotkey docker compose up -d
```

Replace `my_wallet` and `my_hotkey` with your actual wallet name and hotkey.

---

## 🛍️ Shopify Stores API validation (new)

Validators use first‑party coupon APIs instead of any browser automation.

- Detection
  - If a site provides an `api_url` like `https://store.myshopify.com/apps/coupon-check?code={CODE}`, the validator prefers this API.
  
- Flow
  - The validator calls the API with your code (`{CODE}` replaced).
  - No browser automation is used.

- Decision rules
  - A coupon is treated as valid only if the API reports it as applicable (e.g., `ok=true` and `applicable=true`).

- Fallback
  - If no API is configured or the API is unavailable, the validator may skip verification for that site until an API is provided.

---

## 🔒 TLS Notary coupon validation (new)

TLS Notary (TLSN) provides cryptographic proofs of HTTP exchanges without running a browser.

**Purpose**: Confirm coupon claims using cryptographic proofs of real HTTP exchanges, without a browser.

**Actors**:
- Miner who submitted the coupon (provides the proof)
- Validator (requests and checks the proof)
- Local verifier (judges proof validity)

**Flow**:
1. The validator asks the coupon's miner to produce a proof.
2. The miner acknowledges the request and begins generating the proof.
3. The validator briefly checks whether a result is available now; if it is, the validator verifies it locally and decides the coupon's status.
4. If no result is ready, the coupon remains unchanged for a later cycle.

**Decision**:
- Valid proof → mark coupon valid.
- Invalid proof → mark coupon invalid.
- No proof by the deadline (a short grace window since last check or creation) → consider the claim abandoned, release ownership so others can submit.

**Stored insight**:
- When a proof is verified, the validator preserves key context (who the server was, when it happened, what was exchanged) alongside the coupon for auditability.

**Principles**:
- Lightweight (no browser automation).
- Miner-responsibility (the submitter must substantiate the claim).
- Fairness over time (stale, unproven claims don't block others).

For detailed architecture information, see: [BitKoop Miner Architecture](https://github.com/BitKoopLabs/BitKoop-Miner/blob/main/docs/architecture.md)

Local verifier source: [tlsn-http-verifier](https://github.com/BitKoopLabs/tlsn-http-verifier)

## Configuration

Most settings can be changed via environment variables used by `docker-compose.yml`:

- `PORT`: API port (default `8000`)
- `WALLET_NAME`, `WALLET_HOTKEY`, `WALLET_PATH`: Your Bittensor wallet info
- `SUBTENSOR_NETWORK`: Bittensor network (e.g., `finney`)

---

## Requirements

- Docker and Docker Compose
- (Advanced) Python 3.9+ if running without Docker


