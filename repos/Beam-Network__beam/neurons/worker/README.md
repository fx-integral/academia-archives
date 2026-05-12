# Beam Network Worker

A worker node for the Beam Network — an open coordination layer for distributed data transfer built on Bittensor.

Workers receive data transfer tasks, fetch chunks from a source, deliver them to a destination, and report completion with bandwidth metrics.

## Requirements

- Python 3.10+
- CPU: 2+ cores
- RAM: 4 GB+
- Storage: 20 GB SSD
- Network: 100 Mbps symmetric (upload/download)
- OS: Ubuntu 22.04+ / Debian 12+ / macOS 13+

## Installation

From the repository root (recommended — matches subnet dependencies):

```bash
pip install -e "."
```

The worker runtime also relies on packages declared in [`pyproject.toml`](../../pyproject.toml); for a minimal manual install:

```bash
pip install bittensor httpx websockets
```

## Usage

From repository root, `cd neurons/worker`, then:

```bash
# Default wallet
python worker.py

# Custom wallet
python worker.py --wallet.name my_wallet --wallet.hotkey my_hotkey

# Testnet
python worker.py --subtensor.network test
```

## Transport

The worker uses BeamCore HTTP only for registration and signed bootstrap calls. Transfer runtime uses **worker-gateway** WebSockets (`BUFFER_URL` must be the gateway HTTP/WebSocket origin, not BeamCore Core).

Typical environment:

```bash
export SUBNET_CORE_URL=https://beamcore-dev.b1m.ai
export BUFFER_URL=http://localhost:8001   # worker-gateway URL, or your deployed gateway
export CONNECTION_MODE=auto               # or websocket (see worker.py)
python worker.py --subtensor.network test
```

## How It Works

1. Registers with the network using your Bittensor wallet (signed authentication)
2. Connects to `worker-gateway` via WebSocket to receive tasks instantly as they are assigned
3. For each task: fetches data chunks from the source and delivers them to the destination
4. Reports completion with proof-of-bandwidth metrics (bytes transferred, speed, duration)
5. Sends periodic heartbeats to stay registered

## Environment Variables

| Variable            | Required | Description |
| ------------------- | -------- | ----------- |
| `SUBNET_CORE_URL`   | no       | BeamCore HTTP base (defaults per `--subtensor.network` inside `worker.py`). |
| `BUFFER_URL`        | **yes**  | Worker-gateway base URL (`http(s)://host:port` — used to derive WebSocket URLs). |
| `CONNECTION_MODE`   | no       | `websocket` / `polling` / `auto` (default `websocket` in env). Transfer path expects gateway WebSockets. |
