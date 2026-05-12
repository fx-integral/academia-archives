![Flamewire Cover](./flamewire-cover.png)
# SN97 - FlameWire: Decentralized Infrastructure

![Subnet 97 Badge](https://img.shields.io/badge/Subnet-97-blue)

**FlameWire** is a specialized **subnet within the Bittensor network** designed to provide **decentralized RPC, node, and API services** for multiple blockchains.

Like Alchemy, Ankr, or other infrastructure providers—but fully decentralized FlameWire democratizes blockchain infrastructure access, beginning with **Ethereum**, **Bittensor**, and **SUI**, and expanding further.

---

## Quick Navigation

| Section | Description |
|---------|-------------|
| [Key Components](#key-components) | Overview of Miners, Validators, and Subnet Owner roles |
| [Economic Model](#economic-model) | Tokenomics and reward structure |
| [Setup for Miners and Validators](#setup-for-miners-and-validators) | Registration and setup instructions |
| [Competitive Advantages](#competitive-advantages) | Key benefits of FlameWire |
| [Development Directions](#development-directions) | Future roadmap and planned features |

---

## Overview

- **Decentralized infrastructure** for RPC and API services  
- **Multi-chain support**: Ethereum, Bittensor, SUI (and more coming)  
- **Scalable, secure, and resilient** architecture  
- Designed for developers, validators, and network operators

---

## Key Components

### Miners  
Provide the underlying infrastructure:

- **Multi-Chain Node Operators**: Serve Ethereum, Bittensor, SUI, etc.  
- **Global Coverage**: Deploy nodes across regions for low-latency access  
- **Redundant Infrastructure**: Ensures continuous service availability  
- **Secure Communication**: Verified via cryptographic signatures  
- **Scalability**: Easily extend node capacity as demand grows  

### Validators  
Ensure performance and honesty of the network:

- **Uptime Monitoring**: Ensure consistent availability of nodes  
- **Integrity Verification**: Validate correctness of RPC/API responses  
- **Performance Evaluation**: Monitor latency, reliability, and throughput  
- **Weight Allocation**: Assign performance-based rewards  
- **Honesty Checks**: Detect and penalize misbehavior or downtime  

### Subnet Owner  
Coordinates and manages network activity:

- **Traffic Direction**: Distributes API/RPC requests to optimal nodes  
- **Access Management**: Controls permissions for users and developers  
- **Network Optimization**: Improves performance and resource efficiency  

---

## Economic Model

- **Free Public Tier**: Every onboarded chain includes a rate-limited public RPC tier to ensure baseline ecosystem access.
- **Premium Credits Model**: API key–based access with pay-as-you-go credits. Billing is method-tiered and enforces predictable commercial QoS.
- **Performance-Weighted Emissions**: Miner and validator rewards are distributed in ALPHA based strictly on measurable performance (correctness, uptime, latency).
- **Chain Weight Allocation**: Economic incentives scale according to foundation commitments, public contributions, and real premium demand signals.
- **Revenue Recycling Loop**: All premium revenue and commitments are recycled into the ecosystem, with default buyback-and-burn of ALPHA unless governance decides otherwise.

---

## Setup for Miners and Validators

### Registration 

To register as a miner or validator on FlameWire subnet, follow these steps:

1. **Install Bittensor**
   ```bash
   pip install bittensor-cli
   ```

2. **Create a Wallet**
   ```bash
   btcli wallet new --wallet.name flamewire_wallet
   ```

3. **Register Neuron**
   ```bash
   btcli subnet register --wallet.name flamewire_wallet --wallet.hotkey default --subtensor.network finney --subnet.netuid 97
   ```

4. **Verify Registration**
   ```bash
   btcli subnet list --subtensor.network finney --subnet.netuid 97
   ```
### Miners 

FlameWire miner node registration follows the dashboard-based flow in docs:
https://docs.flamewire.io/docs/miners/registration

Supported chain:
- Bittensor nodes only (Ethereum and Sui support are planned).

Prerequisites:
- A full-archive Bittensor node running and fully synced
- Node reachable from the internet
- A wallet with a registered hotkey on subnet 97
- `btcli` installed
- On the node machine, install signing dependencies:
  ```bash
  sudo apt install -y libclang-dev clang curl build-essential
  cargo install subkey --git https://github.com/paritytech/polkadot-sdk
  ```

Node configuration requirements:
- Open ports `9944` (WebSocket RPC) and `30333` (P2P)
- Start your node with `--rpc-methods=unsafe`
- Use a `ws://` or `wss://` endpoint URL

Registration steps:
1. Open the FlameWire app and sign in:
   ```text
   https://app.flamewire.io/login?redirect=%2Fnodes%3Fregister%3Dtrue
   ```
2. In the registration modal, enter your node URL (example `ws://your_node_ip:9944`) and your hotkey.
3. On the node machine, sign the verification message using the node key (not the hotkey):
   ```bash
   echo -n "verify:[hotkey]" | subkey sign \
     --scheme ed25519 \
     --suri "0x$(cat /path-to/chains/bittensor/network/secret_ed25519 | xxd -p -c 32)"
   ```
   Notes:
   - Replace `[hotkey]` with your SS58 hotkey address (starts with `5`).
   - Replace `/path-to/chains/bittensor/network/secret_ed25519` with your node's actual key path.
4. Paste in the modal:
   - `Hotkey`: your SS58 hotkey address (starts with `5`)
   - `Signature`: output from the `subkey sign` command
5. Click `+ Register Node`.

Example sign command:
```bash
echo -n "verify:5ExampleHotkeyAddress" | subkey sign \
  --scheme ed25519 \
  --suri "0x$(cat /var/lib/bittensor/chains/bittensor/network/secret_ed25519 | xxd -p -c 32)"
```

After registration:
- FlameWire runs automatic checks for connectivity, sync status, and archive data.
- In the dashboard, `Healthy` means the node is ready to receive traffic.

Common issues:
- Node not reachable: confirm ports `9944` and `30333` are open.
- Invalid signature: confirm the message is exactly `verify:[hotkey]`, `echo -n` is used, and the node key path is correct.
- Node not syncing: wait until full sync completes.
- WebSocket connection failed: confirm `--rpc-methods=unsafe` is enabled.

Monitor your miner status from the FlameWire dashboard and subnet metagraph:
```bash
btcli subnet metagraph --subtensor.network finney --subnet.netuid 97
```

### Validators

Validator guide reference:
https://docs.flamewire.io/docs/validators/guide

Validators on FlameWire:
- Probe miners for uptime, correctness, and latency
- Aggregate scores into weights
- Publish weights on-chain using `set_weights`

Getting started:
1. Install prerequisites (`Python 3.10+`, `Node.js 18+`).
2. Clone repository:
   ```bash
   git clone https://github.com/unitone-labs/FlameWire.git
   cd FlameWire
   ```
3. Create and activate virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -e .
   npm install -g pm2
   ```
5. Verify validator identity in dashboard:
   ```text
   https://app.flamewire.io/validators?verify=true
   ```
   Sign command:
   ```bash
   btcli w sign --wallet.name [name] --wallet.hotkey [hotkey] --use-hotkey --message verify-validator
   ```
   Then submit:
   - Hotkey address (starts with `5`)
   - Signature output from the command
6. Create validator API key:
   ```text
   https://app.flamewire.io/api-keys?create=true&role=validator
   ```
7. Configure environment:
   ```bash
   cp .env.example .env
   ```
   Required values:
   - `WALLET_NAME`
   - `WALLET_HOTKEY`
   - `SUBTENSOR_NETWORK`
   - `REFERENCE_RPC_URL` (recommended: your own archive endpoint for truth checks)
   - `GATEWAY_URL`
   - `VALIDATOR_API_KEY`
   - `VALIDATOR_MAX_WORKERS`
   - `VALIDATOR_EMA_ALPHA`
   - `VALIDATOR_VERIFICATION_INTERVAL`
   - `WANDB_API_KEY`
8. Start validator:
   ```bash
   pm2 start neurons/validator.py --name flamewire-validator --interpreter python3
   ```
9. Monitor operations:
   ```bash
   pm2 monit
   pm2 logs flamewire-validator
   pm2 restart flamewire-validator
   pm2 status
   pm2 stop flamewire-validator
   pm2 delete flamewire-validator
   pm2 save
   pm2 startup
   ```

Notes:
- Default verification cycle is 480s (8 minutes).
- Verifications run in parallel (default workers: 32).
- Keep wallet credentials and API keys private; never commit `.env`.

### Evaluation and Rewards

- Validators assign scores and weights to miners
- Node score uses weighted performance metrics:
  - `correctness`: 40% (binary, 0 or 1)
  - `uptime`: 30% (passed health checks / total checks measured by this validator)
  - `latency`: 30% (relative response speed measured by this validator)
- Correctness is zero-tolerance:
  - Any failed validation check sets correctness to `0` for that node.
  - If correctness is `0`, the node score is forced to `0`.
- Miner score uses regional factors:
  - Regional multiplier: `clamp(33.33% / actual_region_share, 0.5, 2.0)`
  - Diminishing returns per miner/region: node `N` contributes `node_score * (1/N)`
  - Diversity bonus: `1.00` (1 region), `1.10` (2 regions), `1.20` (3 regions)
  - Raw miner score: `(regional_score_us + regional_score_eu + regional_score_as) * diversity_bonus`
- EMA smoothing:
  - `ema = alpha * raw + (1 - alpha) * previous_ema`
  - `alpha = 0.1` by default.
- Metric and region weights are subnet policy constants in code (not validator `.env` overrides).
- Final chain weights are distributed pro-rata to miner scores and set after each full verification cycle.
- User payments re-enter the subnet economy  

---

## Competitive Advantages

- **True Decentralization**: No central point of control or failure  
- **Cost Efficiency**: Competition reduces access costs  
- **Global Availability**: Regional node access ensures speed and uptime  
- **Resilient Architecture**: Built-in redundancy across providers  
- **Unified Multi-Chain Access**: One platform for multiple blockchains  
- **Stake-Driven Free Access**: Lowers barriers for new users  

---

## Development Directions

- Expansion to additional blockchains  
- Introduction of chain-specific APIs  
- Enhanced monitoring and analytics tools  
- Foundation partnerships 
- AI-based optimization of request routing  
