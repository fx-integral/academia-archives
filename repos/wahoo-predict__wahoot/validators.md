# Validating on Wahooτ

### Getting Started (The Quick Version)

Register on the subnet:

```bash
btcli subnets register --netuid 30 --wallet.name WALLET_NAME --hotkey WALLET_HOTKEY
```

Make sure you've got the standard Bittensor validator requirements covered (stake weight, validator permit) and you're ready to roll.

### Validator Flow

The validator runs a continuous loop that:

1. **Syncs metagraph** – Gets current network state (active UIDs, hotkeys, axons)
2. **Fetches Wahooτ data** – Pulls trading stats from Wahooτ API for all registered traders
3. **Queries traders** – Requests predictions from active traders on the subnet
4. **Calculates rewards** – Scores traders using EMA-based scoring (volume, profit, win rate)
5. **Sets weights** – Posts weights to blockchain to distribute TAO rewards

The loop interval is automatically calculated from the metagraph tempo, ensuring perfect synchronization with the network.

### How We Score Everyone

We keep the scoring simple and transparent. Every miner gets evaluated on three things:

- **Total Volume (USD)** – Are they actually trading, or just sitting there?
- **Realized Profit (USD)** – Are they making money, or losing it?
- **Win Rate** – Are their predictions actually good, or are they just guessing?

| Variable | Description | Default |
|----------|-------------|---------|
| `WALLET_NAME` | Bittensor wallet name (coldkey) | **Required** |
| `HOTKEY_NAME` | Bittensor hotkey name | **Required** |
| `NETUID` | Subnet UID | **Required** |
| `NETWORK` | Bittensor network (`finney` or `test`) | `finney` |
| `USE_VALIDATOR_DB` | Enable database caching and EMA score persistence | `false` |
| `VALIDATOR_DB_PATH` | Database file path (each validator gets their own) | `~/.wahoo/validator.db` |
| `CHAIN_ENDPOINT` | Custom chain endpoint URL | None (advanced use only) |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

**Important Notes:**
- **API endpoints are hardcoded** in the validator code (not configurable)
  - Wahooτ API: `https://api.wahoopredict.com`
  - Validation endpoint: `https://api.wahoopredict.com/api/v2/event/bittensor/statistics`
- **Loop interval is automatically calculated** from metagraph tempo (synced with network)
  - Calculated as: `tempo * block_time * 1.1` (with 10% buffer)
  - Recalculates each iteration in case tempo changes
  - Falls back to 3600 seconds if tempo unavailable
- **Database auto-initializes** at validator start (schema created automatically)
  - Each validator gets their own database file
  - Set `VALIDATOR_DB_PATH` environment variable to use a custom location
  - Database uses SQLite with NORMAL synchronous mode (local file)

### Installation & Setup

**Simple 3-step setup:**
1. Clone repo and install with UV
2. Set your wallet keys
3. Start validator

#### Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended)
- **Unix/Linux system** (macOS or Linux)
- **SQLite 3** (usually pre-installed)
- **Virtual environment** (recommended: `uv` , `venv`, or `virtualenv`)

#### Installation Options

**Option 1: Using `uv` (Recommended - Fastest)**

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone <repository-url>
cd wahoot

# Create virtual environment and install
uv venv
source .venv/bin/activate  # On macOS/Linux
uv pip install -e .  # Install production dependencies
```

#### Step 2: Set Up Your Wallet Keys

**You need a Bittensor wallet with coldkey and hotkey:**

1. **Create wallet (if needed):**
   ```bash
   btcli wallet new_coldkey --wallet.name <your_wallet_name>
   btcli wallet new_hotkey --wallet.name <your_wallet_name> --wallet.hotkey <your_hotkey_name>
   ```

2. **Register on the subnet:**
   ```bash
   btcli wallet register --netuid <your_subnet_uid> --wallet.name <your_wallet_name> --wallet.hotkey <your_hotkey_name>
   ```

3. **Set environment variables:**
   ```bash
   export WALLET_NAME=<your_wallet_name>
   export HOTKEY_NAME=<your_hotkey_name>
   export NETUID=30
   export NETWORK=finney  # or "test" for testnet
   ```

**Note**: You can also create a `.env` file within the root of the repository to hold the arguments read by the validator. If you set environment variables in your shell, these are only set for the current session and do not persist.

#### Step 3: Initialize (Optional)

The validator will auto-initialize on first run, but you can manually initialize:

```bash
python -m wahoo.validator.init
```

This sets up the database schema. The validator will auto-initialize if needed.

#### Step 4: Start the Validator

**That's it! Just run:**

```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # or: source venv/bin/activate

# Start the validator as a background processs
nohup python -m wahoo.entrypoints.validator > wahoo-validator.log 2>&1 &
```

**Or with explicit arguments:**
```bash
nohup python -m wahoo.entrypoints.validator \
  --wallet.name your_wallet_name \
  --wallet.hotkey your_hotkey_name \
  --netuid 30 \
  --network finney \
  > wahoo-validator.log 2>&1 &
```

If you want to use pm2 instead of nohup, then please use the following format:

```bash
pm2 start python --name wahoo-validator -- -m wahoo.entrypoints.validator
```

**What happens when you start:**

1. ✅ **Auto-initializes database** - Creates schema if database doesn't exist (each validator gets their own database file)
2. ✅ **Loads your wallet** from `~/.bittensor/wallets/` using the provided wallet/hotkey names
3. ✅ **Connects to Bittensor network** (mainnet `finney` or `test` testnet)
4. ✅ **Syncs metagraph** to get current network state (UIDs, hotkeys, axons)
5. ✅ **Calculates loop interval** from metagraph tempo (automatically synced with network)
6. ✅ **Initializes ValidatorDB** (if `USE_VALIDATOR_DB=true`) for caching and EMA score persistence
7. ✅ **Enters main loop** - continuously:
   - Syncs metagraph each iteration
   - Fetches trading data from Wahooτ API for all registered traders
   - Caches validation data in database (if enabled)
   - Queries traders for predictions
   - Calculates rewards using EMA-based scoring
   - Persists EMA scores to database (if enabled)
   - Sets weights on blockchain

**Network Selection:** Use `--network finney` for mainnet (production) or `--network test` for testnet (testing).

**Prerequisites:** Bittensor wallet created and registered on subnet, with `WALLET_NAME`, `HOTKEY_NAME`, and `NETUID` configured.
