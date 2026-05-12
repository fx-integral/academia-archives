# Cartha CLI

**The official command-line tool for Cartha subnet miners.** Cartha is the Liquidity Provider for 0xMarkets DEX. A simple, powerful way to manage your mining operations—from registration to tracking your locked funds.

## Why Cartha CLI?

Cartha CLI makes mining on the Cartha subnet effortless. As the Liquidity Provider for 0xMarkets DEX, Cartha enables miners to provide liquidity and earn rewards:

- **🔐 One-Click Registration** - Get started mining in minutes
- **📊 Instant Status Updates** - See all your pools, balances, and expiration dates at a glance
- **⏰ Smart Expiration Warnings** - Never miss a renewal with color-coded countdowns
- **💼 Multi-Pool Management** - Track multiple trading pairs in one place
- **🔒 Secure Authentication** - Session-based authentication with your Bittensor hotkey

## Installation

```bash
pip install cartha-cli
```

## Quick Start

```bash
# Show available commands
cartha --help

# Get started with registration
cartha miner register --help

# Check your miner status (no authentication needed)
cartha miner status --help

# Check CLI health and connectivity
cartha utils health

# Or use short aliases
cartha m status
cartha v lock
cartha u health
```

## Requirements

- Python 3.11
- Bittensor wallet within btcli
    - learn how to create/import one here https://docs.learnbittensor.org/keys/working-with-keys

## What You Can Do

### Get Started

**Register your miner:**
```bash
cartha miner register --wallet-name your-wallet --wallet-hotkey your-hotkey
```

**Check your status anytime:**
```bash
cartha miner status --wallet-name your-wallet --wallet-hotkey your-hotkey
# Or use the short alias: cartha m status
```
> **Track Your Miner Status**
> See all your active trading pairs, balances, and when they expire—all in one command. The CLI shows you:
> - Which pools are active and earning rewards
> - How much you have locked in each pool
> - Days remaining before expiration (with helpful warnings)
> - Which pools are included in the next reward epoch

### View Available Pools

See all available pools with their pool IDs and vault addresses:

```bash
cartha vault pools
# Or use: cartha v pools
```

This shows you which pools are available, their full pool IDs, vault contract addresses, and chain IDs.

### Lock Your Funds to start Mining

Create a new lock position with the streamlined lock flow:
```bash
cartha vault lock \
  --coldkey your-wallet \
  --hotkey your-hotkey \
  --pool-id BTCUSD \
  --amount 1000.0 \
  --lock-days 30 \
  --owner-evm 0xYourEVMAddress \
  --chain 8453 \
  --vault-address 0xVaultAddress
# Or use: cartha v lock
```

**Parameter Notes:**
- `--owner` and `--owner-evm` are interchangeable (EVM address that will own the lock)
- `--vault` and `--vault-address` are interchangeable (vault contract address)
- `--network` accepts `test` (netuid 78) or `finney` (netuid 35, default)
- `--chain` or `--chain-id` are interchangeable (EVM chain ID: 84532 for Base Sepolia testnet)

The CLI will:
1. Check your registration on the specified network (subnet 35 for finney, subnet 78 for test)
2. Authenticate with your Bittensor hotkey
3. Request a signed LockRequest from the verifier
4. Automatically open the Cartha Lock UI in your browser with all parameters pre-filled (you can also paste the url into your browser manually)
5. Guide you through Phase 1 (Approve USDC) and Phase 2 (Lock Position) via the web interface
6. Automatically detect when approval completes and proceed to Phase 2
7. The verifier automatically detects your lock and adds you to the upcoming epoch

**Managing Positions**: Visit https://liquidity.0xmarkets.io/manage to view all your positions, extend locks, or top up existing positions.

### Check Your Setup

Verify your CLI is configured correctly and can reach all services:

```bash
cartha utils health
# Or use the short alias
cartha u health
```

This checks:
- Verifier connectivity and latency
- Bittensor network connectivity
- Configuration validation
- Subnet metadata
- Environment variables

Use `cartha utils health --verbose` (or `cartha u health --verbose`) for detailed troubleshooting information.

## Need Help?

- **[Full Command Reference](docs/COMMANDS.md)** - Complete guide to all commands
- **[Testnet Guide](testnet/README.md)** - Getting started on testnet
- **[Feedback & Support](docs/FEEDBACK.md)** - Questions or suggestions?

## Contributing

We welcome contributions! Please see our [Feedback & Support](docs/FEEDBACK.md) page for ways to get involved.

---

**Made with ❤ by General Tensor**
