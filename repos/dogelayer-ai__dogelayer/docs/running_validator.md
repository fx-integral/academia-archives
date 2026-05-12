# DogeLayer Validator Setup

This guide will walk you through setting up and running a DogeLayer validator on the Bittensor network.

DogeLayer enables Scrypt miners (LTC/DOGE) to contribute hashpower to a collective mining pool. All miners direct their hashpower to a single subnet pool, where validators evaluate and rank miners based on the share value they generate.

Validators are rewarded in DogeLayer's subnet-specific (alpha) token on the Bittensor blockchain, which represents *stake* in the subnet. This alpha stake can be exited from the subnet by unstaking it to TAO (Bittensor's primary currency).

**Share value** is the difficulty at which the miner solved a blockhash. The higher the difficulty solved, the more incentive a miner gets during *emissions*, the process by which Bittensor periodically distributes tokens to participants based on the Yuma Consensus algorithm. In general, the higher the hashpower, the higher the share value submitted.

See also:

- [Introduction to DogeLayer](../README.md)
- [Introduction to Bittensor](https://docs.learnbittensor.org/learn/introduction)
- [Yuma Consensus](https://docs.learnbittensor.org/yuma-consensus/)
- [Emissions](https://docs.learnbittensor.org/emissions/)

> **Deployment note:** We recommend using Docker + Docker Compose for validators. This ensures your validator code is always up-to-date and simplifies deployment.

## Prerequisites

### Server Requirements

**Recommended Configuration:**
- **CPU**: 2 cores minimum
- **RAM**: 8 GB minimum
- **Storage**: 200 GB SSD
- **Network**: Stable internet connection with low latency
- **OS**: Ubuntu 20.04 LTS or later (or any Linux distribution with Docker support)

### Other Requirements

- A Bittensor wallet with coldkey and hotkey, registered on DogeLayer subnet 80
- Sufficient TAO stake (minimum ~0.5 TAO, recommended 5-10 TAO)
- Subnet proxy configuration (pre-configured, no setup needed)
- Docker Engine 24+ and Docker Compose

Bittensor Docs:

- [Requirements for Validation](https://docs.learnbittensor.org/validators/#requirements-for-validation)
- [Validator registration](https://docs.learnbittensor.org/validators/index.md#validator-registration)
- [Wallets, Coldkeys and Hotkeys in Bittensor](https://docs.learnbittensor.org/getting-started/wallets)

## Setup Steps

### 1. Bittensor Wallet Setup

Check your wallet, or create one if you have not already.

Bittensor Documentation: [Creating/Importing a Bittensor Wallet](https://docs.learnbittensor.org/working-with-keys)

#### List wallet
```bash
btcli wallet list
```
```console
Wallets
├── Coldkey YourColdkey  ss58_address 5F...
│   ├── Hotkey YourHotkey  ss58_address
│   │   5E...
```

#### Check your wallet's balance

```bash
btcli wallet balance \
  --wallet.name <your wallet name> \
  --subtensor.network finney
```

```console
                             Wallet Coldkey Balance
                                  Network: finney

    Walle…   Coldkey Address                             Free…   Stake…   Total…
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    your_…   5DvSxCaMW9tCPBS4TURmw4hDzXx5Bif51jq4baC6…   …       …        …



    Total…                                               …       …        …
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2. Register on DogeLayer Subnet 80

```bash
btcli subnet register \
  --netuid 80 \
  --wallet.name YOUR_WALLET \
  --wallet.hotkey YOUR_HOTKEY \
  --subtensor.network finney
```

### 3. Stake TAO (Required)

Validators need sufficient stake to set weights:

```bash
# Stake TAO to your validator
btcli stake add \
  --wallet.name YOUR_WALLET \
  --wallet.hotkey YOUR_HOTKEY \
  --amount 10.0 \
  --subtensor.network finney

# Check stake status
btcli wallet overview \
  --wallet.name YOUR_WALLET \
  --netuid 80 \
  --subtensor.network finney
```

**Stake Requirements**:
- **Minimum**: ~0.5 TAO (to meet minimum weight threshold of 0.0005 TAO)
- **Recommended**: 5-10 TAO (for stable operation)
- **Validator Permit**: May require more depending on competition

### 4. Clone Repository

```bash
# Clone the repository
git clone https://github.com/dogelayer-ai/dogelayer.git
cd dogelayer
```

### 5. Configuration

Navigate to the validator directory and create a `.env` file:

```bash
cd dogelayer/validator
cp env.example .env
nano .env
```

Update the `.env` file with your wallet information:

```env
# Bittensor Configuration
NETUID=80
SUBTENSOR_NETWORK=finney
BT_WALLET_NAME=your_wallet_name
BT_WALLET_HOTKEY=your_hotkey_name

# Subnet Proxy Configuration (pre-configured)
# Note: This is a shared API token for all validators
SUBNET_PROXY_API_URL="http://dogelayer-205dd0511d5781e4.elb.ap-southeast-1.amazonaws.com:8889"
SUBNET_PROXY_API_TOKEN="2z1gLMqF6yZuf9G56iCLi5H6lKPMWJ_kgiYp-61_gAI"

# Optional: Database submission
SUBMIT_VALIDATOR_INFO=true
DB_SUBMIT_INTERVAL_SECONDS=300
LOGGING_LEVEL=info
```

**Note for Subnet Owner**: If you are the subnet owner, you need to additionally configure pool parameters to publish pool information to the chain. Regular validators should NOT set these:

```env
# Subnet Owner ONLY - Uncomment if you are the subnet owner
# PROXY_DOMAIN="dogelayer-205dd0511d5781e4.elb.ap-southeast-1.amazonaws.com"
# PROXY_PORT="3331"
# PROXY_HIGH_DIFF_PORT="3332"
# PROXY_API_PORT="8889"
# PROXY_USERNAME="latent-to"
# PROXY_PASSWORD="x"
# PROXY_API_TOKEN="2z1gLMqF6yZuf9G56iCLi5H6lKPMWJ_kgiYp-61_gAI"
```

### 6. Running the Validator

#### Using Docker Compose (Recommended)

1. **Ensure Docker is installed**  
   Get more details here: https://docs.docker.com/engine/install/

2. **Ensure your wallet is accessible**  
   Make sure your Bittensor wallet is in `~/.bittensor/wallets/`

3. **Start the validator**
   ```bash
   docker compose down && docker compose pull && docker compose up -d && docker compose logs -f
   ```

4. **Verify it's running**  
   The validator should start and you should see info logs showing it's scoring miners.



## Important Parameters

- `netuid`: Set to 80 for DogeLayer subnet
- `subtensor.network`: Set to `finney` for mainnet
- `wallet.name`: Your Bittensor wallet name
- `wallet.hotkey`: Your wallet's hotkey

## Validator Evaluation Process

1. Validators fetch miner statistics from the subnet proxy every evaluation interval
2. They calculate share values based on miner contributions (LTC/DOGE mining)
3. Weights are set every `tempo` blocks (every epoch) based on moving averages
4. All validators use the same proxy endpoint for consistent evaluation

## Managing Your Validator

### View Logs
```bash
docker compose logs -f
```

### Stop Validator
```bash
docker compose down
```

### Restart Validator
```bash
docker compose restart
```

### Update Validator
```bash
docker compose down
docker compose pull
docker compose up -d
```

## Monitoring

### Check Validator Status
```bash
# Check if container is running
docker compose ps

# View recent logs
docker compose logs --tail=100

# Check resource usage
docker stats dogelayer-validator
```

### Check Weights on Chain
```bash
btcli subnet metagraph \
  --netuid 80 \
  --subtensor.network finney
```

## Troubleshooting

**Cannot connect to subnet proxy**
- Verify the `SUBNET_PROXY_API_URL` is correct
- Check that your API token is valid
- Ensure network connectivity to the proxy

**No miner data received**
- Confirm miners are actively mining
- Check proxy logs for any issues with data collection
- Verify network connectivity between validators and the subnet proxy

**Wallet issues**
- Ensure wallet is properly created and registered
- Check that wallet path is correct (`~/.bittensor/wallets/`)
- Verify you're using the correct network (finney)
- Ensure wallet files have correct permissions (600)

**Insufficient stake error (Custom Error 1)**
- Your stake is below the minimum threshold
- Stake more TAO to your validator hotkey
- Minimum: ~0.5 TAO, Recommended: 5-10 TAO

**Docker issues**
- Ensure Docker daemon is running
- Check Docker Compose version (24+)
- Verify wallet volume mount is correct
- Check container logs for specific errors

## Rewards

Validators earn two types of rewards:

### 1. TAO Rewards (Bittensor Protocol - Automatic)
- Automatically distributed to your hotkey
- Based on your validator performance and stake
- Check balance: `btcli wallet balance --wallet.name YOUR_WALLET`

### 2. LTC/DOGE Mining Revenue Share (Manual Withdrawal - Secondary Distribution)

**Important**: LTC/DOGE mining rewards go through **secondary distribution**. The platform collects all mining revenue and redistributes it to both miners and validators based on their contributions.

#### Withdrawal Process for Validators

1. **Login to DogeLayer Website**
   - Visit the DogeLayer platform: https://dogelayer.ai/
   - Connect using your Bittensor coldkey wallet (use the same coldkey that corresponds to your validator hotkey)
   - Ensure you're using the correct validator wallet

2. **Set Withdrawal Addresses**
   - Navigate to account settings or wallet management
   - Add your LTC address (starts with 'L', 'M', or 'ltc1')
   - Add your DOGE address (starts with 'D')
   - **Verify addresses carefully** to avoid loss of funds
   - Complete address verification process

3. **View Your Balance**
   - Check your accumulated LTC/DOGE earnings from validation
   - View distribution history
   - Monitor pending withdrawals

4. **Submit Withdrawal Request**
   - Select cryptocurrency (LTC or DOGE)
   - Enter withdrawal amount (minimum: LTC 0.01, DOGE 100)
   - Review withdrawal address and network fees
   - Submit withdrawal request (creates a withdrawal ticket)
   - Wait for processing: 1-3 business days

**Important Notes**:
- Mining rewards are collected by the platform and redistributed (secondary distribution)
- **Both validators and miners** must set withdrawal addresses on the website
- Withdrawals require manual submission, not automatic
- Large withdrawals may require additional verification
- First withdrawal may take longer for security review
- Keep transaction records for your reference

## Support

- GitHub Issues: https://github.com/dogelayer-ai/dogelayer/issues
- Bittensor Discord: Subnet 80 channel

Happy validating!
