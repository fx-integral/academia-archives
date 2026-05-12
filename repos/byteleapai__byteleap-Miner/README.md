# ByteLeap Miner - Bittensor SN128 Compute Network

ByteLeap Miner is the resource aggregation component of the ByteLeap distributed compute platform. Miners connect to the Bittensor network (SN128), aggregate worker resources, and earn rewards through active compute leases and computational challenges.

## Architecture Overview

**Three-tier system:**
- **Validator**: Network coordination and scoring validation
- **Miner**: Resource aggregation and Bittensor network interface (this component)
- **Worker**: Hardware monitoring and compute task execution (separate repository)

## Scoring System

Miners earn rewards through two main factors:

### Score Components (Weighted)
- **Lease Revenue** (100%): Active compute rentals generate the primary score
- **Availability Multiplier**: Based on 169-hour online presence

### How Scoring Works

**Lease Revenue**
- Workers with active compute rentals earn lease scores
- Idle workers score zero on this component
- Integrated with compute marketplace APIs

**Worker Management**
- Maximum 100 workers per miner
- Challenges target only unleased workers
- Final score sums all worker performance (capped at 100)

## Quick Start

### Prerequisites
- Python 3.8+
- Bittensor wallet with registered hotkey

### Installation
```bash
# Setup environment
python3 -m venv venv
source ./venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration
Configure your setup in:
- `config/miner_config.yaml` - Network settings, wallet, worker management

### Running the Miner

**Start Miner** (aggregates workers, communicates with Bittensor):
```bash
python scripts/run_miner.py --config config/miner_config.yaml
```

### For production use, please run it with PM2.

Start Miner:
```bash
pm2 start ecosystem.config.js
```

**Note**: Workers should be deployed separately using the byteleap-Worker repository.

## Technical Architecture

```
┌────────────────────────┐                       ┌───────────────────┐                   ┌────────────────────────┐
│       Validator        │                       │       Miner       │                   │       Worker(s)        │
│      (Bittensor)       │       Encrypted       │    (Bittensor)    │                   │                        │
│                        │ ←── Communication ─── │                   │ ←── WebSocket ──→ │ • System Monitoring    │
│ • Challenge Creation   │    (via bittensor)    │ • Worker Mgmt.    │      (1 : N)      │ • Challenge Execution  │
│ • Score Validation     │                       │ • Resource Agg.   │                   │ • VMGW Session         │
│ • Weight Calculation   │                       │ • Task Routing    │                   │ • Libvirt Mgmt.        │
└────────────────────────┘                       └───────────────────┘                   └────────────────────────┘
```

### Core Components

**Miner** (`neurons/miner/`)
- Worker lifecycle management via WebSocket
- Resource aggregation and reporting
- Bittensor network communication
- Challenge distribution and result collection

**Shared Libraries** (`neurons/shared/`)
- Cryptographic challenge protocols
- Merkle tree verification system
- Configuration management
- Network communication utilities

## License

MIT License - see the [LICENSE](LICENSE) file for details.