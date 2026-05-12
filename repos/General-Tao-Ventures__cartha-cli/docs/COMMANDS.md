# Cartha CLI Command Reference

Complete documentation for all Cartha CLI commands and their arguments.

**Cartha is the Liquidity Provider for 0xMarkets DEX.** This CLI enables miners to provide liquidity and manage their mining operations on the Cartha subnet.

## Table of Contents

- [Command Groups](#command-groups)
- [Miner Commands](#miner-commands)
  - [cartha miner register](#cartha-miner-register)
  - [cartha miner status](#cartha-miner-status)
- [Vault Commands](#vault-commands)
  - [cartha vault pools](#cartha-vault-pools)
  - [cartha vault lock](#cartha-vault-lock)
- [Utility Commands](#utility-commands)
  - [cartha utils health](#cartha-utils-health)
  - [cartha utils config](#cartha-utils-config)
- [Other Commands](#other-commands)
  - [cartha version](#cartha-version)
- [Environment Variables](#environment-variables)
- [Common Workflows](#common-workflows)

---

## Command Groups

The CLI is organized into logical command groups with short aliases:

- **`cartha miner`** (or **`cartha m`**) - Miner management commands
- **`cartha vault`** (or **`cartha v`**) - Vault management commands
- **`cartha utils`** (or **`cartha u`**) - Utility commands (health checks and configuration)

---

## Miner Commands

### cartha miner register

Register a hotkey on the Cartha subnet to start mining.

#### Usage

**Interactive mode (recommended - will prompt for wallet):**

```bash
cartha miner register
# or
cartha m register
```

**With arguments (skip prompts):**

```bash
cartha miner register [OPTIONS]
# or
cartha m register [OPTIONS]
```

#### Options (All Optional - Will Prompt if Not Provided)

| Option | Aliases | Type | Description |
| --- | --- | --- | --- |
| `--wallet-name` | `--wallet.name`, `--coldkey`, `-w` | string | Coldkey wallet name |
| `--wallet-hotkey` | `--wallet.hotkey`, `--hotkey`, `-wh` | string | Hotkey name within the wallet |
| `--network` | `-n` | string | Bittensor network name (default: `finney`) |
| `--netuid` | *(none)* | integer | Subnet netuid (default: `35`) |
| `--pow` | *(none)* | flag | Use PoW registration instead of burned registration |
| `--cuda` | *(none)* | flag | Enable CUDA for PoW registration |

#### Examples

```bash
# Interactive mode (recommended)
cartha miner register

# With short aliases
cartha m register -w cold -wh hot

# Using --coldkey/--hotkey aliases
cartha miner register --coldkey cold --hotkey hot

# Register with PoW
cartha miner register -w cold -wh hot --pow --cuda

# Specify network explicitly
cartha miner register -w cold -wh hot -n finney --netuid 35
```

#### What It Does

1. Loads your wallet and validates hotkey ownership
2. Checks if the hotkey is already registered
3. Performs registration (burned TAO or PoW)
4. Retrieves the assigned UID from the metagraph
5. Confirms successful registration

**Note:** After registration, you can immediately start creating lock positions using `cartha vault lock`.

---

### cartha miner status

Check your miner status and pool information **without requiring authentication**. This is the fastest way to check your miner's status, active pools, expiration dates, and verification status. As a Liquidity Provider for 0xMarkets DEX, this shows your liquidity positions and mining status.

#### Usage

```bash
cartha miner status [OPTIONS]
# or
cartha m status [OPTIONS]
```

#### Options (All Optional - Will Prompt if Not Provided)

| Option | Aliases | Type | Description |
| --- | --- | --- | --- |
| `--wallet-name` | `--wallet.name`, `--coldkey`, `-w` | string | Coldkey wallet name |
| `--wallet-hotkey` | `--wallet.hotkey`, `--hotkey`, `-wh` | string | Hotkey name within the wallet |
| `--slot` | `--uid`, `-u` | integer | Subnet UID assigned to the miner (auto-fetched if not provided) |
| `--auto-fetch-uid` | *(none)* | flag | Automatically fetch UID from Bittensor network (default: enabled) |
| `--network` | `-n` | string | Bittensor network name (default: `finney`) |
| `--netuid` | *(none)* | integer | Subnet netuid (default: `35`) |
| `--json` | *(none)* | flag | Emit the raw JSON response |
| `--refresh` | *(none)* | flag | If position not found, manually trigger verifier to process a lock transaction |
| `--tx-hash` | `--tx`, `--transaction` | string | Transaction hash to refresh (used with `--refresh`). If not provided, will prompt for input |

#### Examples

```bash
# Interactive mode (recommended)
cartha miner status

# Quick status check with aliases
cartha m status -w cold -wh hot

# Using --coldkey/--hotkey aliases
cartha miner status --coldkey cold --hotkey hot

# Using full names
cartha miner status --wallet-name cold --wallet-hotkey hot

# With explicit slot UID (skip auto-fetch)
cartha miner status -w cold -wh hot -u 123

# JSON output
cartha miner status -w cold -wh hot --json

# Manually trigger verifier to process a lock transaction
cartha miner status -w cold -wh hot --refresh --tx 0x1234...

# Refresh with full names
cartha miner status \
  --wallet-name cold \
  --wallet-hotkey hot \
  --refresh \
  --tx-hash 0x1234567890abcdef...
```

#### Output

The command displays:

- **Miner Status Table:**
  - Hotkey address
  - Slot UID
  - State (active, verified, pending, unknown)
  - EVM Addresses - Shows all EVM addresses used across your positions:
    - Single address: Shows full address
    - 2-3 addresses: Shows all addresses (one per line)
    - 4+ addresses: Shows count (e.g., "4 addresses") - see pool details below for individual addresses

- **Active Pools Table** (if pools exist):
  - **Each row represents one lock position**
  - Pool name (human-readable, e.g., "EURUSD", "BTCUSDC")
  - Amount locked (USDC)
  - Lock days
  - Expiration date with days remaining countdown
    - ⚠ Red warning if < 7 days remaining
    - ⚠ Yellow warning if < 15 days remaining
  - Status (Active / In Next Epoch)
  - EVM address used for that specific position
  - **Note**: Multiple rows may show the same Pool ID if you have positions using different EVM addresses

- **Reminders:**
  - Lock expiration behavior
  - Top-up/extension information
  - Multi-pool guidance (if applicable)

#### Key Features

- ✅ **No authentication required** - Fast status checks without signature verification
- ✅ **Multi-pool support** - View all your active pools in one command
- ✅ **Expiration countdown** - See days remaining with color-coded warnings
- ✅ **Auto-fetches UID** - No need to remember your slot UID
- ✅ **Manual refresh** - Trigger immediate verifier processing if position not found (with `--refresh`)

#### What It Does

1. Loads your wallet to get the hotkey address
2. Automatically fetches your slot UID from the Bittensor network (or prompts if disabled)
3. Queries the verifier's public `/v1/miner/status` endpoint (no signature required)
4. Displays comprehensive miner and pool information
5. Shows expiration warnings for pools expiring soon
6. **If `--refresh` is used and position not found:**
   - Prompts for transaction hash (or uses `--tx-hash` if provided)
   - First checks `GET /lock/status` to see if transaction is already verified
   - Only if `verified: false`, triggers `POST /lock/process` to manually process the transaction
   - Re-fetches miner status and displays updated results
   - This avoids unnecessary on-chain polling if the transaction is already verified

#### Manual Refresh Feature

The `--refresh` flag is useful when:
- You just created a lock transaction and want immediate processing instead of waiting for the automatic hint watcher (which polls every 30 seconds)
- The automatic hint watcher missed your transaction for some reason
- You want to verify that your transaction was successfully processed

**How it works:**
1. First checks if the transaction is already verified (to avoid unnecessary on-chain polling)
2. Only triggers manual processing if the transaction hasn't been verified yet
3. Waits a moment for the database to update
4. Re-fetches and displays your updated miner status

**Example workflow after creating a lock:**
```bash
# Create a lock position
cartha vault lock --coldkey cold --hotkey hot --pool-id BTCUSD --amount 100 --lock-days 30 --owner-evm 0x... --chain-id 84532 --vault-address 0x...

# If the verifier didn't detect it immediately, manually trigger processing
cartha miner status --wallet-name cold --wallet-hotkey hot --refresh --tx-hash 0xYourTransactionHash
```

---

## Vault Commands

### cartha vault pools

Show current available pools with their pool IDs, vault addresses, and chain IDs.

#### Usage

```bash
cartha vault pools [OPTIONS]
# or
cartha v pools [OPTIONS]
```

#### Options

| Option | Type | Description |
| --- | --- | --- |
| `--json` | flag | Emit responses as JSON |

#### Examples

```bash
# List all available pools
cartha vault pools
# or
cartha v pools

# JSON output format
cartha vault pools --json
```

#### Output

The command displays all available pools in a multi-line format:

- **Pool Name**: Human-readable pool identifier (e.g., "BTCUSD", "ETHUSD")
- **Pool ID**: Full hex pool ID (66 characters: `0x` + 64 hex characters)
- **Vault Address**: Full vault contract address (42 characters: `0x` + 40 hex characters)
- **Chain ID**: EVM chain ID where the vault is deployed

#### Example Output

```
Available Pools

Pool 1: BTCUSD
  Pool ID:      0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489
  Vault Address: 0x471D86764B7F99b894ee38FcD3cEFF6EAB321b69
  Chain ID:     84532

Pool 2: ETHUSD
  Pool ID:      0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45
  Vault Address: 0xdB74B44957A71c95406C316f8d3c5571FA588248
  Chain ID:     84532

Pool 3: EURUSD
  Pool ID:      0xa9226449042e36bf6865099eec57482aa55e3ad026c315a0e4a692b776c318ca
  Vault Address: 0x3C4dAfAC827140B8a031d994b7e06A25B9f27BAD
  Chain ID:     84532
```

#### When to Use

- Before creating a lock position to see available pools
- To verify pool IDs and vault addresses for a specific pool
- To check which chain a pool is deployed on

---

### cartha vault lock

Create a new lock position by interacting with the Cartha Verifier. This command guides you through the complete lock flow: registration check, authentication, signature request, and transaction execution.

#### Usage

**Interactive mode (recommended - will prompt for all inputs):**

```bash
cartha vault lock
# or
cartha v lock
```

**With arguments (skip prompts):**

```bash
cartha vault lock [OPTIONS]
# or
cartha v lock [OPTIONS]
```

#### Options (All Optional - Will Prompt if Not Provided)

| Option | Aliases | Type | Description |
| --- | --- | --- | --- |
| `--wallet-name` | `--wallet.name`, `--coldkey`, `-w` | string | Coldkey wallet name |
| `--wallet-hotkey` | `--wallet.hotkey`, `--hotkey`, `-wh` | string | Hotkey name within the wallet |
| `--pool-id` | `--pool`, `--poolid`, `-p` | string | Pool name (BTCUSD, ETHUSD) or hex ID (0x...) |
| `--amount` | `-a` | string | Amount of USDC to lock (e.g., '100.0') |
| `--lock-days` | `--days`, `-d` | integer | Number of days to lock (7-365) |
| `--owner-evm` | `--owner`, `--evm-address`, `--evm`, `-e` | string | EVM address that will own the lock position |
| `--chain-id` | `--chain`, `--chainid` | integer | EVM chain ID (auto-detected from pool) |
| `--vault-address` | `--vault` | string | CarthaVault contract address (auto-detected from pool) |
| `--json` | *(none)* | flag | Emit responses as JSON |

#### Examples

```bash
# Interactive mode (recommended for beginners)
cartha vault lock

# The CLI will prompt you for:
# - Coldkey wallet name
# - Hotkey name
# - Pool (just type: BTCUSD, ETHUSD, etc.)
# - Amount in USDC
# - Lock days
# - EVM address

# Short aliases (for power users)
cartha v lock -w cold -wh hot -p BTCUSD -a 100 -d 30 -e 0xYourEVM...

# Full argument names
cartha vault lock \
  --wallet-name cold \
  --wallet-hotkey hot \
  --pool BTCUSD \
  --amount 100.0 \
  --days 30 \
  --owner-evm 0xYourEVM...

# Using --coldkey/--hotkey aliases (also works)
cartha vault lock \
  --coldkey cold \
  --hotkey hot \
  --pool-id BTCUSD \
  --amount 100 \
  --lock-days 30 \
  --owner 0xYourEVM...

# Chain and vault auto-detected from pool (no need to specify)
# But you can override if needed:
cartha vault lock \
  -w cold -wh hot -p BTCUSD -a 100 -d 30 -e 0xEVM... \
  --chain-id 84532 \
  --vault 0xVaultAddress...
```

#### What It Does

1. **Registration Check**: Verifies your hotkey is registered on the Bittensor subnet
2. **Bittensor Authentication**: Signs a challenge message with your hotkey and receives a session token
3. **Request Signature**: Sends lock parameters to the verifier, which signs an EIP-712 LockRequest
4. **User Confirmation**: Displays lock details and prompts for confirmation
5. **Open Frontend**: Automatically opens the Cartha Lock UI in your browser with pre-filled transaction parameters
6. **Phase 1 - Approve USDC**: The frontend guides you through approving USDC spending. The CLI automatically detects when approval is complete
7. **Phase 2 - Lock Position**: The frontend guides you through locking your USDC in the vault contract
8. **Auto-Processing**: Verifier automatically detects `LockCreated` events and adds miner to upcoming epoch

**Note**: The CLI opens a web interface (Cartha Lock UI) that handles both approval and lock transactions. You'll connect your wallet (MetaMask, Coinbase Wallet, Talisman, or WalletConnect) and execute the transactions directly in the browser. The CLI monitors the approval phase and automatically proceeds when complete.

**Multiple Positions**: You can create multiple lock positions on the same pool by using different EVM addresses. Each position is tracked separately with its own amount, lock period, and expiration. However, if you try to create a second lock on the same pool with the same EVM address, it will be rejected. Use the top-up feature at https://liquidity.0xmarkets.io/manage to add more USDC to an existing position or extend its lock period.

#### Troubleshooting

##### Signature Mismatch / Funds Locked But Not Credited

If you request a new signature after already requesting one, the old signature becomes invalid. If you execute a transaction using an old signature:

- ✅ **Transaction will succeed** - Your funds are safely locked in the vault contract
- ❌ **Miner won't be credited** - The verifier won't automatically match the transaction to your miner

**What to do:**

1. **Open a support ticket** on our Discord channel

2. **Provide the following information:**
   - Transaction hash (0x...)
   - Your Bittensor hotkey (SS58 address)
   - Your miner slot UID
   - Chain ID and vault address
   - Pool ID
   - EVM address (owner address)

3. **Prove ownership with signatures:**
   
   **Bittensor Hotkey Signature:**
   ```bash
   btcli w sign --wallet.name <your-coldkey> --wallet.hotkey <your-hotkey> --text "Cartha lock recovery: <tx-hash>"
   ```
   Provide both the signature and the message text.
   
   **EVM Address Signature:**
   Sign the following message with MetaMask or your Web3 wallet:
   ```
   Cartha lock recovery: <tx-hash>
   ```
   Provide both the signature and the message text.

4. **Admin will verify signatures** and manually recover your lock to credit your miner

**Prevention:**

- Always use the **most recent signature** from `cartha vault lock`
- If you request a new signature, discard the old one
- Don't execute transactions with old signatures after requesting new ones

---

## Utility Commands

### cartha utils health

Check CLI health: verifier connectivity, Bittensor network, and configuration.

This command verifies that all components needed for the CLI are working correctly. Use this command to diagnose connectivity issues or verify your configuration before using other commands.

#### Usage

```bash
cartha utils health [OPTIONS]
# or
cartha u health [OPTIONS]
```

#### Options

| Option | Type | Description |
| --- | --- | --- |
| `--verbose`, `-v` | flag | Show detailed troubleshooting information for failed checks |

#### Examples

```bash
# Basic health check
cartha utils health
# or
cartha u health

# Detailed health check with troubleshooting tips
cartha utils health --verbose
```

#### Output

The command performs five checks:

1. **Verifier Connectivity**
   - Tests connection to the configured verifier URL
   - Measures response latency
   - Verifies the verifier is reachable and responding

2. **Bittensor Network Connectivity**
   - Connects to the configured Bittensor network
   - Fetches current block number
   - Measures network latency
   - Validates network is operational

3. **Configuration Validation**
   - Verifies verifier URL format
   - Checks network is set
   - Validates netuid is positive
   - Reports any configuration issues

4. **Subnet Metadata**
   - Retrieves subnet information from the metagraph
   - Shows number of registered slots
   - Displays tempo (epoch length)
   - Shows current block number
   - Measures metadata fetch latency

5. **Environment Variables**
   - Checks which environment variables are set vs using defaults
   - Shows count of configured variables
   - In verbose mode, displays each variable's value and source

#### Exit Codes

- `0`: All checks passed (or warnings only)
- `1`: One or more checks failed

#### When to Use

- Before running other commands to verify connectivity
- When troubleshooting connection issues
- After changing configuration to verify settings
- As a quick diagnostic tool

---

### cartha utils config

Manage CLI configuration through environment variables. This command provides an easy interface to view and modify configuration without manually editing files.

#### Usage

```bash
# View all configuration options (default action)
cartha utils config
# or
cartha u config

# List all configuration options
cartha utils config list

# Set a configuration variable
cartha utils config set <VARIABLE_NAME> <value>

# Get information about a specific variable
cartha utils config get <VARIABLE_NAME>

# Remove a configuration variable (revert to default)
cartha utils config unset <VARIABLE_NAME>
```

#### Subcommands

**`list`** - Display all available configuration variables with their descriptions, current values, and sources (default/environment/.env file).

**`set <VARIABLE_NAME> <value>`** - Set a configuration variable. This writes to a `.env` file in your project directory.

**`get <VARIABLE_NAME>`** - Display detailed information about a specific configuration variable, including its current value and description.

**`unset <VARIABLE_NAME>`** - Remove a configuration variable from the `.env` file, reverting to the default value.

#### Examples

```bash
# View all configuration options (same as 'list')
cartha utils config

# List all variables
cartha utils config list

# Set the verifier URL
cartha utils config set CARTHA_VERIFIER_URL https://cartha-verifier-826542474079.us-central1.run.app

# Set the network
cartha utils config set CARTHA_NETWORK finney

# Set the netuid
cartha utils config set CARTHA_NETUID 35

# Get info about a specific variable
cartha utils config get CARTHA_VERIFIER_URL

# Remove a custom setting (revert to default)
cartha utils config unset CARTHA_EVM_PK
```

#### Available Configuration Variables

All configuration variables are listed in the [Environment Variables](#environment-variables) section below.

---

## Other Commands

### cartha version

Display the current version of the Cartha CLI.

#### Usage

```bash
cartha version
```

#### Output

Shows the installed CLI version number.

---

## Environment Variables

The following environment variables can be set to configure the CLI:

| Variable | Description | Default |
| --- | --- | --- |
| `CARTHA_VERIFIER_URL` | Verifier endpoint URL | `https://cartha-verifier-826542474079.us-central1.run.app` |
| `CARTHA_NETWORK` | Bittensor network name | `finney` |
| `CARTHA_NETUID` | Subnet netuid | `35` |
| `CARTHA_LOCK_UI_URL` | Cartha Lock UI frontend URL | `https://liquidity.0xmarkets.io` |
| `CARTHA_BASE_SEPOLIA_RPC` | Base Sepolia RPC endpoint for approval detection (optional) | `None` (uses public endpoint) |
| `CARTHA_EVM_PK` | EVM private key for local signing (optional) | - |
| `CARTHA_RETRY_MAX_ATTEMPTS` | Maximum number of retry attempts for failed requests | `3` |
| `CARTHA_RETRY_BACKOFF_FACTOR` | Exponential backoff multiplier between retries | `1.5` |
| `BITTENSOR_WALLET_PATH` | Override wallet path if keys are not in the default location | - |

### Setting Environment Variables

The easiest way to manage environment variables is using the `cartha utils config` command:

```bash
# View all available variables and their descriptions
cartha utils config

# Set a variable (writes to .env file)
cartha utils config set CARTHA_VERIFIER_URL https://cartha-verifier-826542474079.us-central1.run.app
cartha utils config set CARTHA_NETWORK finney
cartha utils config set CARTHA_NETUID 35

# Get information about a specific variable
cartha utils config get CARTHA_VERIFIER_URL

# Remove a variable
cartha utils config unset CARTHA_EVM_PK
```

**Alternative methods:**

```bash
# Linux/macOS - export in shell
export CARTHA_VERIFIER_URL="https://cartha-verifier-826542474079.us-central1.run.app"
export CARTHA_NETWORK="finney"
export CARTHA_NETUID="35"

# Windows (PowerShell)
$env:CARTHA_VERIFIER_URL="https://cartha-verifier-826542474079.us-central1.run.app"
$env:CARTHA_NETWORK="finney"
$env:CARTHA_NETUID="35"

# Manual .env file (create in project root)
CARTHA_VERIFIER_URL=https://cartha-verifier-826542474079.us-central1.run.app
CARTHA_NETWORK=finney
CARTHA_NETUID=35
CARTHA_RETRY_MAX_ATTEMPTS=3
CARTHA_RETRY_BACKOFF_FACTOR=1.5
```

### Retry Logic

The CLI automatically retries failed requests to improve reliability:

- **Automatic Retries**: Failed requests are automatically retried up to 3 times (configurable)
- **Exponential Backoff**: Wait time between retries increases exponentially (1.5x multiplier)
- **Retry Conditions**: Retries occur for:
  - Network timeouts
  - Connection errors
  - HTTP 5xx server errors (500, 502, 503, 504)
- **Non-Retryable**: 4xx client errors (400, 401, 403, 404) are not retried

**Example**: With default settings, retry delays are:
- Attempt 1: Immediate
- Attempt 2: Wait 1.5 seconds
- Attempt 3: Wait 2.25 seconds

You can customize retry behavior via environment variables:
```bash
export CARTHA_RETRY_MAX_ATTEMPTS=5
export CARTHA_RETRY_BACKOFF_FACTOR=2.0
```

---

## Common Workflows

### First-Time Setup

1. **Register your hotkey:**
   ```bash
   cartha miner register --wallet-name cold --wallet-hotkey hot
   ```
   Note your assigned UID for reference.

2. **Check your miner status:**
   ```bash
   cartha miner status --wallet-name cold --wallet-hotkey hot
   ```
   This shows your status without requiring authentication.

3. **Configure environment variables (optional):**
   ```bash
   cartha utils config
   cartha utils config set CARTHA_NETWORK finney
   ```
   See available configuration options and set them as needed.

### Creating a Lock Position

1. **Start the lock flow:**
   ```bash
   cartha vault lock \
     --coldkey my-coldkey \
     --hotkey my-hotkey \
     --pool-id BTCUSD \
     --amount 250.0 \
     --lock-days 30 \
     --owner-evm 0xYourEVMAddress \
     --chain-id 8453 \
     --vault-address 0xVaultAddress
   ```

2. **The CLI automatically opens the Cartha Lock UI** in your browser with all parameters pre-filled

3. **Connect your wallet** (MetaMask, Coinbase Wallet, Talisman, or WalletConnect) - make sure it matches the `--owner-evm` address

4. **Phase 1 - Approve USDC**: The frontend guides you through approving USDC spending. The CLI automatically detects when approval completes

5. **Phase 2 - Lock Position**: The frontend guides you through locking your USDC in the vault contract

6. **Wait for auto-detection** - The verifier will automatically detect your `LockCreated` event and add you to the upcoming epoch

**⚠️ Important:** 
- Make sure the wallet you connect in the frontend matches the `--owner-evm` address specified in the CLI
- The frontend includes wallet validation to prevent using the wrong address
- If you request a new signature after already requesting one, make sure to use the **newest signature only**. Using an old signature will lock your funds but won't credit your miner automatically. In this case, open a support ticket on Discord for manual recovery. You'll need to provide:
  - Transaction hash and all lock details
  - Bittensor hotkey signature (via `btcli w sign`)
  - EVM address signature (via MetaMask or Web3 wallet)

### Checking Pool Status and Expiration

1. **Quick status check (no authentication):**
   ```bash
   cartha miner status --wallet-name cold --wallet-hotkey hot
   ```

2. **View all your pools:**
   - See all active pools in one table
   - Check expiration dates with days remaining countdown
   - Identify pools expiring soon (red/yellow warnings)
   - View EVM addresses used for each pool

3. **Monitor expiration:**
   - Pools expiring in < 7 days show red warning
   - Pools expiring in < 15 days show yellow warning
   - Expired pools stop earning rewards automatically

### Extending Your Lock Period

1. **Check your current lock status:**
   ```bash
   cartha miner status --wallet-name cold --wallet-hotkey hot
   ```

2. **Use the Cartha Lock UI to extend or top up:**
   - Visit the Cartha Lock UI: https://liquidity.0xmarkets.io/manage
   - Navigate to "My Positions" to view your existing locks
   - Click "Extend" or "Top Up" buttons for the position you want to modify
   - Follow the on-screen instructions to complete the transaction
   - The verifier automatically detects `LockUpdated` events
   - Your updated amount/lock_days will be reflected in `miner status` within 30 seconds

**Note**: Extend Lock and Top Up features are currently in testing and may not work properly yet. If you encounter issues, contact support on Discord.

### Multi-Pool Management

1. **View all pools:**
   ```bash
   cartha miner status --wallet-name cold --wallet-hotkey hot
   ```

2. **Each pool is tracked separately:**
   - Each pool has its own expiration date
   - Expired pools stop earning rewards, others continue
   - You can have multiple pools active simultaneously
   - Each pool can use a different EVM address

---

## Troubleshooting

### Wallet Not Found

Ensure your Bittensor wallet files exist in the default location or set `BITTENSOR_WALLET_PATH`:

```bash
export BITTENSOR_WALLET_PATH="/path/to/your/wallets"
```

### Configuration Issues

Use the config command to view and set environment variables:

```bash
# View all configuration options
cartha utils config

# Set a specific variable
cartha utils config set CARTHA_VERIFIER_URL https://your-verifier-url.com
```

### Signature Generation Fails

- Ensure `eth-account` is installed: `pip install eth-account`
- For local signing, verify `CARTHA_EVM_PK` is set correctly
- For external signing, follow the instructions in the generated files

### Verifier Connection Errors

- Check `CARTHA_VERIFIER_URL` is set correctly
- Verify network connectivity
- Check verifier status: `curl $CARTHA_VERIFIER_URL/health`

### UID Auto-Fetch Fails

If automatic UID fetching fails:

1. Check network connectivity to Bittensor network
2. Verify your hotkey is registered: `cartha miner status --no-auto-fetch-uid`
3. Manually provide slot UID: `cartha miner status --slot 123`

---

For more help, see [Feedback & Support](FEEDBACK.md).
