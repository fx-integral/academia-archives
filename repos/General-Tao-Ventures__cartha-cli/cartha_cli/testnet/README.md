# Cartha CLI - Testnet Setup Guide

This guide will help you set up and use the Cartha CLI on the public testnet with real vault contracts.

## Prerequisites

- Python 3.11
- Bittensor wallet (for subnet registration)
- Access to the testnet verifier URL
- Testnet TAO (required for subnet registration)
- EVM wallet (MetaMask or similar) with testnet USDC for locking

## Step 0: Set Up Your EVM Wallet for Base Sepolia Testnet

Before you can lock funds, you need to configure your EVM wallet (MetaMask, Coinbase Wallet, etc.) to connect to Base Sepolia Testnet and get testnet tokens.

### 0.1: Add Base Sepolia Testnet to Your Wallet

**For MetaMask:**

1. Open MetaMask and click the network dropdown (usually shows "Ethereum Mainnet")
2. Click "Add Network" or "Add a network manually"
3. Enter the following network details:

   ```
   Network Name: Base Sepolia
   RPC URL: https://sepolia.base.org
   Chain ID: 84532
   Currency Symbol: ETH
   Block Explorer URL: https://sepolia.basescan.org
   ```

4. Click "Save" to add the network
5. Switch to the "Base Sepolia" network

**For Other Wallets:**

- **Coinbase Wallet**: Go to Settings → Networks → Add Network, then enter the details above
- **WalletConnect-compatible wallets**: Use the same network details when connecting

**Quick Add (MetaMask):**

You can also use the [Chainlist](https://chainlist.org/) website:
1. Visit https://chainlist.org/
2. Search for "Base Sepolia"
3. Click "Connect Wallet" and approve the connection
4. Click "Add to MetaMask" and confirm

### 0.2: Get Testnet ETH for Gas Fees

You'll need testnet ETH on Base Sepolia to pay for transaction gas fees. Get it from the official Optimism Superchain faucet:

1. **Visit the Optimism Superchain Faucet**: https://console.optimism.io/faucet
2. **Connect your wallet** (MetaMask or WalletConnect)
3. **Select "Base Sepolia"** from the network dropdown
4. **Enter your wallet address** (or it will auto-detect from your connected wallet)
5. **Click "Request Tokens"** or similar button
6. **Wait for confirmation** - You should receive testnet ETH within a few minutes

**Note**: The faucet may have rate limits (e.g., once per 24 hours per address). If you need more testnet ETH, you may need to wait or use a different address.

**Alternative Faucets** (if the main faucet is unavailable):
- Check Base Sepolia documentation for additional faucet options
- Join the Cartha Discord/Telegram for community faucet links

### 0.3: Get Testnet USDC Tokens

Testnet USDC is required to lock funds in the Cartha vaults. You can claim testnet USDC from the Cartha faucet.

**To Get Testnet USDC:**

1. **Visit the Cartha Faucet**: https://liquidity.0xmarkets.io/faucet
2. **Connect your wallet** (MetaMask, Coinbase Wallet, Talisman, or WalletConnect)
3. **Make sure you're on Base Sepolia network** (Chain ID: 84532)
4. **Click "Claim USDC"** button
5. **Approve the transaction** in your wallet
6. **Wait for confirmation** - You should receive 1,000,000 testnet USDC within a few minutes

**Faucet Details**:
- **Claim Amount**: 1,000,000 USDC per claim
- **Cooldown**: 24 hours between claims (per wallet address)
- **Network**: Base Sepolia (Chain ID: 84532)

**Note**: The faucet has a 24-hour cooldown period. After claiming, you'll need to wait 24 hours before you can claim again from the same wallet address.

**Testnet USDC Contract Address** (for reference):
- Base Sepolia: `0x2340D09c348930A76c8c2783EDa8610F699A51A8`

You can verify you received USDC by:
- Checking your wallet balance (should show USDC)
- Viewing your address on [BaseScan Sepolia](https://sepolia.basescan.org/)

### Getting Testnet TAO

You'll need testnet TAO to register your hotkey to the subnet. Get testnet TAO from the faucet:

🔗 **Testnet TAO Faucet**: <https://app.minersunion.ai/testnet-faucet>

Simply visit the faucet and request testnet TAO to your wallet address. You'll need TAO in your wallet to pay for subnet registration.

## Installation

Install the Cartha CLI from PyPI:

```bash
pip install cartha-cli
```

Verify the installation:

```bash
cartha --help
```

## Testnet Configuration

### Environment Variables

Set the following environment variables:

```bash
# Required: Testnet verifier URL
export CARTHA_VERIFIER_URL="https://cartha-verifier-826542474079.us-central1.run.app"

# Required: Bittensor network configuration
export CARTHA_NETWORK="test"  # Use "test" for testnet
export CARTHA_NETUID=78       # Testnet subnet UID

# Optional: Custom wallet path
export BITTENSOR_WALLET_PATH="/path/to/wallet"
```

### Verify Configuration

```bash
# Check CLI can access verifier
cartha --help

# Test verifier connectivity
curl "${CARTHA_VERIFIER_URL}/health"
```

## Testnet Workflow

### Step 1: Verify Your EVM Wallet Setup

Before proceeding, make sure you have:

- ✅ Base Sepolia network added to your wallet
- ✅ Testnet ETH in your wallet (for gas fees)
- ✅ Testnet USDC in your wallet (contact team if needed)

You can verify your balances:
- Check ETH balance in your wallet
- Check USDC balance (should show as a token in your wallet)
- View on [BaseScan Sepolia](https://sepolia.basescan.org/address/YOUR_ADDRESS) to see all tokens

### Step 2: Register Your Hotkey

Register your hotkey to the testnet subnet:

```bash
cartha miner register \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --network test \
  --netuid 78
```

This will:

- Register your hotkey to subnet 78 (testnet)
- Fetch your slot UID
- Display your registration details

**Save the output** - you'll need your slot UID.

### Step 3: Lock Funds Using Cartha Lock UI

Use the streamlined lock flow with the Cartha Lock UI:

```bash
cartha vault lock \
  --coldkey <your-coldkey-name> \
  --hotkey <your-hotkey-name> \
  --pool-id BTCUSD \
  --amount 100.0 \
  --lock-days 30 \
  --owner-evm 0xYourEVMAddress

# Note: --chain-id and --vault-address are optional - CLI auto-matches them from pool-id!
```

This command will:

1. **Check Registration**: Verify your hotkey is registered on the subnet
2. **Authenticate**: Sign a challenge message with your Bittensor hotkey to get a session token
3. **Request Signature**: Get an EIP-712 LockRequest signature from the verifier
4. **Open Cartha Lock UI**: Automatically opens the web interface in your browser with all parameters pre-filled
5. **Phase 1 - Approve USDC**: Connect your wallet and approve USDC spending through the frontend. The CLI automatically detects when approval completes
6. **Phase 2 - Lock Position**: Lock your USDC in the vault contract through the frontend
7. **Auto-Detection**: The verifier automatically detects your `LockCreated` event and adds you to the upcoming epoch

**Important Notes**:
- Make sure you're connected to **Base Sepolia** network in your wallet (not Mainnet!)
- You'll need testnet USDC in your EVM wallet (contact team if you don't have any)
- The frontend supports MetaMask, Coinbase Wallet, Talisman, and WalletConnect
- Make sure the wallet you connect matches the `--owner-evm` address specified in the CLI
- The frontend includes wallet validation to prevent using the wrong address

**Transaction Flow**:
1. **Approve USDC**: First transaction approves the vault to spend your USDC (handled in frontend)
2. **Lock Position**: Second transaction locks your USDC in the vault (handled in frontend)
3. Both transactions require gas fees (paid in testnet ETH)

**Managing Existing Positions**:
- Visit https://liquidity.0xmarkets.io/manage to view all your locks
- Use "Extend" or "Top Up" buttons to modify existing positions

### Step 4: Check Miner Status

Verify your miner status (no authentication required):

```bash
cartha miner status \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name>

# Or with explicit slot UID
cartha miner status \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --slot <your-slot-uid>
```

This will show:

- Miner state and pool information
- All active pools with amounts and expiration dates
- Days remaining countdown (with warnings for expiring pools)

## Pool IDs and Vault Addresses

Pool IDs can be specified as either:
- **Human-readable names**: `BTCUSD`, `EUR/USD`, `ETH/USD`, etc.
- **Hex strings**: `0x...` (32 bytes)

The CLI automatically converts readable names to hex format and matches them to the correct vault address.

### Available Testnet Pools (Base Sepolia)

| Pool Name | Pool ID (hex) | Vault Address |
|-----------|---------------|---------------|
| BTCUSD | `0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489` | `0x471D86764B7F99b894ee38FcD3cEFF6EAB321b69` |
| ETH/USD | `0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45` | `0xdB74B44957A71c95406C316f8d3c5571FA588248` |
| EUR/USD | `0xa9226449042e36bf6865099eec57482aa55e3ad026c315a0e4a692b776c318ca` | `0x3C4dAfAC827140B8a031d994b7e06A25B9f27BAD` |

**Note**: When using `cartha vault lock`, you can simply specify `--pool-id BTCUSD` and the CLI will automatically:
- Match the correct vault address for that pool
- Match the correct chain ID (Base Sepolia: 84532)

You don't need to manually specify `--vault-address` or `--chain-id` unless you want to override them.

See `testnet/pool_ids.py` for the complete pool mappings and helper functions.

## Common Commands

### Check CLI Version

```bash
cartha version
```

### View Help

```bash
cartha --help
cartha miner register --help
cartha vault lock --help
cartha miner status --help
```

### Register (Burned Registration)

```bash
cartha miner register \
  --wallet-name <name> \
  --wallet-hotkey <hotkey> \
  --network test \
  --netuid 78 \
  --burned
```

## Troubleshooting

### "Verifier URL not found"

**Problem**: CLI can't connect to verifier

**Solution**:

```bash
# Verify environment variable is set
echo $CARTHA_VERIFIER_URL

# Test verifier connectivity
curl "${CARTHA_VERIFIER_URL}/health"

# If using a different URL, update it
export CARTHA_VERIFIER_URL="https://cartha-verifier-826542474079.us-central1.run.app"
```

### "Hotkey not registered"

**Problem**: Hotkey is not registered on the subnet

**Solution**:

- Register your hotkey first using `cartha miner register`
- Verify you're using the correct network (`test`) and netuid (`78`)
- Check that you have testnet TAO in your wallet

### "Wallet not found"

**Problem**: CLI can't find your Bittensor wallet

**Solution**:

```bash
# Check default wallet location
ls ~/.bittensor/wallets/

# Or set custom path
export BITTENSOR_WALLET_PATH="/path/to/wallet"
```

### "Network error"

**Problem**: Can't connect to Bittensor network

**Solution**:

- Verify `CARTHA_NETWORK` is set to `"test"` for testnet
- Check your internet connection
- Try using a VPN if network is blocked

### "Transaction failed"

**Problem**: MetaMask transaction failed

**Solution**:

- **Check Network**: Make sure you're on **Base Sepolia** network (not Mainnet or other networks)
- **Check Gas**: Ensure you have enough testnet ETH for gas fees
- **Check USDC**: Ensure you have enough testnet USDC in your wallet
- **Check Approval**: Make sure you've approved the vault to spend USDC (first transaction)
- **Verify Transaction Data**: Check that the transaction data matches what the CLI displayed
- **Check Network Congestion**: Base Sepolia may be slower than mainnet - wait a bit and retry

### "Insufficient funds" or "Not enough ETH"

**Problem**: Don't have enough testnet ETH for gas

**Solution**:

- Visit https://console.optimism.io/faucet
- Select "Base Sepolia" network
- Request testnet ETH to your wallet address
- Wait a few minutes for the transaction to complete
- Retry your transaction

### "USDC balance is zero" or "No USDC found"

**Problem**: Don't have testnet USDC tokens

**Solution**:

- Visit the Cartha faucet at https://liquidity.0xmarkets.io/faucet
- Connect your wallet and claim 1,000,000 testnet USDC
- Note: There's a 24-hour cooldown between claims
- Verify receipt on [BaseScan Sepolia](https://sepolia.basescan.org/)

### "Wrong wallet connected" or "Wallet address mismatch"

**Problem**: The frontend shows a warning that the connected wallet doesn't match the required owner address

**Solution**:

1. **Disconnect your current wallet** using the "Disconnect" button in the frontend
2. **Connect the correct wallet** that matches the `--owner-evm` address you specified in the CLI
3. **Verify the address** - The frontend will show "Required Owner" vs "Connected Wallet" to help you identify the mismatch
4. If you need to use a different address, restart the CLI command with the correct `--owner-evm` address

**Note**: The frontend includes automatic wallet validation to prevent this issue. Always ensure you connect the wallet that matches the address specified in the CLI command.

## Testing Your Setup

### Complete Testnet Checklist

Before starting, make sure you have:

- [ ] Python 3.11 installed
- [ ] `uv` package manager installed
- [ ] Bittensor wallet set up
- [ ] MetaMask (or other EVM wallet) installed
- [ ] Base Sepolia network added to MetaMask
- [ ] Testnet ETH in your wallet (from faucet)
- [ ] Testnet USDC in your wallet (from team)
- [ ] Testnet TAO in your Bittensor wallet (for registration)

### Quick Test

```bash
# 1. Register your hotkey
cartha miner register --wallet-name test --wallet-hotkey test --network test --netuid 78

# 2. Check miner status (no authentication needed)
cartha miner status --wallet-name test --wallet-hotkey test

# 3. Lock funds (interactive flow)
# Note: Make sure you're on Base Sepolia network in MetaMask!
# Chain ID and vault address are auto-detected from pool-id - no need to specify!
cartha vault lock \
  --coldkey test \
  --hotkey test \
  --pool-id BTCUSD \
  --amount 100.0 \
  --lock-days 30 \
  --owner-evm 0xYourEVMAddress
```

**Important**: 
- Chain ID (84532 for Base Sepolia) and vault address are **automatically detected** from the pool ID
- You only need to specify `--pool-id BTCUSD` (or `ETH/USD`, `EUR/USD`)
- The CLI will show you the auto-matched values before proceeding

## Next Steps

- Check the [Main README](../README.md) for advanced usage
- Review [Validator Setup](../../cartha-validator/docs/TESTNET_SETUP.md) if running a validator
- Provide feedback via [GitHub Issues](https://github.com/your-org/cartha-cli/issues)

## Additional Resources

- [CLI README](../README.md) - Full CLI documentation
- `testnet/pool_ids.py` - Pool ID helper functions for converting between readable names and hex format
