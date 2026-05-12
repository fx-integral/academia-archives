# Level114 Bittensor Subnet

A Bittensor subnet that enables miners to register with a collector-center-main service and allows validators to evaluate miner performance based on reported metrics.

## Overview

Level114 is a subnet designed for:
- **Miners**: Register with the collector-center-main service and report performance metrics
- **Validators**: Query miners for metrics and set weights based on performance evaluation

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│                 │    │                  │    │                     │
│   Validators    │◄──►│   Bittensor      │◄──►│      Miners         │
│                 │    │   Network        │    │                     │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
         │                                               │
         │               Query Metrics                   │
         └───────────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────┐
                    │                     │
                    │ Collector-Center    │
                    │ Main Service        │
                    │                     │
                    └─────────────────────┘
```

## Key Features

- **Automatic Registration**: Miners automatically register with collector-center-main
- **Performance Metrics**: Comprehensive system and application metrics collection
- **Decentralized Validation**: Validators independently assess miner performance
- **Weight-based Incentives**: Performance-based reward distribution

## Components

### Miners
- Register with collector-center-main on startup (one-time only)
- Respond to validator queries for basic system metrics  
- Run minimal overhead - just registration and validator response handling

### Validators
- Query miners for performance metrics
- Evaluate miner performance using multiple criteria
- Set weights on the Bittensor network based on performance scores

### Collector Integration
- Miners register with collector-center-main service on startup (one-time)
- No background reporting or periodic tasks
- Simple HTTP POST registration with signature verification
- Validators query collector service independently for metrics

## Requirements

### System Requirements
- **Python**: 3.8 or higher
- **OS**: Linux (Ubuntu/Debian recommended), macOS, or Windows
- **RAM**: Minimum 2GB, recommended 4GB+
- **Disk Space**: At least 1GB free space
- **Network**: Stable internet connection for Bittensor network communication

### Python Dependencies
- `bittensor >= 9.0.0`
- `torch >= 1.12.0` 
- `requests >= 2.28.0`
- `aiohttp >= 3.8.0`
- `uvloop >= 0.17.0` (Linux/macOS only)

See `pyproject.toml` for complete dependency list.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/level114/level114-subnet.git
cd level114-subnet
```

2. Install dependencies:
```bash
pip install -e .
```

3. Configure your environment:
```bash
cp config.env.example .env
# Edit .env with your configuration
```

## Usage

### Running a Miner

**Important**: The miner registers or unregisters your Minecraft server with the collector-center-main service. The convenience scripts use the hosted collector at `https://collector.level114.io` by default.

Registering via convenience script (recommended):
```bash
./scripts/register_miner.sh --minecraft_hostname play.example.com --wallet.name your_wallet --wallet.hotkey your_hotkey
```

Unregistering:
```bash
./scripts/unregister_miner.sh --minecraft_hostname play.example.com --wallet.name your_wallet --wallet.hotkey your_hotkey
```

Direct python execution:
```bash
python neurons/miner.py \
    --netuid 114 \
    --subtensor.network finney \
    --wallet.name your_wallet \
    --wallet.hotkey your_hotkey \
    --minecraft_hostname play.example.com \
    --action register
```

**What the register action does:**
1. Registers once with the collector-center-main service
2. Saves server credentials (Server ID, API Token) to local files
3. Exits after successful registration - no background processes!

**What the unregister action does:**
1. Signs an unregister request for your hostname and port
2. Notifies collector-center-main to remove the server from active evaluation
3. Stops new validator scoring cycles for that server

**Minecraft Server Rules:**

- The server must be publicly available.
- The server must have the required Level114 plugins installed.
- If a hostname is set, it must match the IP.
- Do not remove OP status for the SN114 user.

Multiple violations of the above rules may result in a permanent blacklist of the coldkey.


### Running a Validator

```bash
./scripts/run_validator.sh --wallet.name your_wallet --wallet.hotkey your_hotkey
```

Or directly:
```bash
python neurons/validator.py \
    --netuid 114 \
    --subtensor.network finney \
    --wallet.name your_wallet \
    --wallet.hotkey your_hotkey \
    --neuron.sample_size 10
```

## Configuration Options

### Miner Options
- `--minecraft_hostname`: Hostname of your Minecraft server (required)
- `--minecraft_port`: Minecraft server port (default: 25565)
- `--action`: `register` (default) or `unregister`
- `--wallet.name`: Your Bittensor wallet name (REQUIRED)
- `--wallet.hotkey`: Your Bittensor wallet hotkey (REQUIRED)

### Validator Options
- `--neuron.sample_size`: Number of miners to query per validation step (default: 10)
- `--validator.query_timeout`: Timeout for miner queries (default: 12.0s)

### Network Options
- `--netuid`: Subnet network UID (default: 114)
- `--subtensor.network`: Bittensor network (finney/test/local)

## Server Credentials

After successful registration, the miner saves important credentials to local files:

### Saved Files
- `credentials/minecraft_server_[wallet]_[hotkey]_[ip].txt` - Human-readable format
- `credentials/minecraft_server_[wallet]_[hotkey]_[ip].json` - JSON format for programmatic use

### Contents
- **Server ID**: Unique identifier for your Minecraft server
- **API Token**: Authentication token for collector-center-main
- **Key ID**: Cryptographic key identifier
- **Server Details**: IP, port, wallet information
- **Registration Time**: When the server was registered

### Security
⚠️ **IMPORTANT**: Keep these files secure! They contain sensitive authentication information.

The `credentials/` directory is automatically added to `.gitignore` to prevent accidental commits.

## Metrics Evaluation

The subnet evaluates miners based on several key metrics:

### Performance Scoring
1. **Uptime Score**: Based on continuous availability and response consistency
2. **Efficiency Score**: Optimal resource usage without being idle
3. **Network Score**: Low latency and good connectivity
4. **Reliability Score**: Low error rates and consistent performance

### Reward Calculation
- Weights are assigned based on normalized performance scores
- Miners must maintain good performance across all metrics
- Bonus rewards for active task completion
- Penalties for high error rates or poor resource management

## Troubleshooting

### Common Issues

#### Miner Registration Problems
**Issue**: Miner fails to register with collector service
- **Check collector IP**: Ensure the collector server IP is correct and reachable
- **Check connectivity**: Test with `ping COLLECTOR_IP` or `telnet COLLECTOR_IP 3000`
- **Check wallet**: Verify your wallet name and hotkey are correct
- **Check network**: Ensure you're on the right network (finney/test/local)

#### Wallet Issues
**Issue**: "Wallet not found" or authentication errors
- **Check wallet path**: Default is `~/.bittensor/wallets`
- **Check wallet name**: Must match exactly (case-sensitive)
- **Check hotkey**: Must exist in your wallet
- **Create wallet**: Use `btcli wallet new_coldkey` and `btcli wallet new_hotkey`

#### Network Connection Issues
**Issue**: Timeout errors or network connectivity problems
- **Check internet**: Verify stable internet connection
- **Check subtensor**: Ensure subtensor network is accessible
- **Check ports**: Verify no firewall blocking required ports
- **Check DNS**: Try using IP addresses instead of domain names

#### Validator Query Issues
**Issue**: Validator can't query miners or gets timeout errors
- **Check query timeout**: Increase `--validator.query_timeout` if needed
- **Check sample size**: Reduce `--neuron.sample_size` if too many failures
- **Check network latency**: High latency can cause timeouts

#### File Permission Issues
**Issue**: Cannot write credential files or access wallet files
```bash
# Fix permissions for credential directory
chmod 755 credentials/
chmod 600 credentials/*

# Fix wallet permissions
chmod 700 ~/.bittensor/wallets/
chmod 600 ~/.bittensor/wallets/*/*
```

#### Environment Configuration
**Issue**: Configuration not loading properly
- **Check .env file**: Ensure it exists and has correct format
- **Check environment variables**: Verify all required variables are set
- **Check file paths**: Use absolute paths when in doubt

### Debug Mode

Enable debug logging for more detailed information:
```bash
# For miners
python neurons/miner.py --logging.debug

# For validators  
python neurons/validator.py --logging.debug
```

### Getting Help

If you encounter issues not covered here:
1. Check the logs for detailed error messages
2. Verify your configuration matches the examples
3. Test on testnet first before mainnet
4. Create a GitHub issue with logs and configuration details

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For support and questions:
- Create an issue on GitHub
- Join our Discord community
- Check the example usage in `/scripts/example_usage.md`

## Disclaimer

This is experimental software. Use at your own risk. Always test on testnet before mainnet deployment.
