# Bittensor Tensorclaw Subnet 92 

## 📌 Project Purpose
This project is a decentralized Large Language Model (LLM) inference subnet built on the Bittensor network.
Its core purpose is to aggregate high-quality LLM API nodes (e.g., OpenAI, DeepSeek, Claude, Llama) globally through Bittensor's incentive mechanism, providing a unified, highly available, and load-balanced compatible API service to the public.

By introducing the **Business API**, this project directly links real commercial API traffic with the miners' Bittensor contribution scores, realizing the principle: "Whoever processes more real requests with high quality receives more TAO rewards."


## 📌 Overview
Welcome to the  release of the Tensorclaw Subnet. We have revolutionized the architecture by replacing the traditional, IP-exposing `Axon/Dendrite` P2P network with a highly robust **Centralized WebSocket Router (AICenter)**.

**Miners now act as pure clients.** They no longer need a public IP, port forwarding, or DDoS protection. They securely connect to the AICenter via WebSockets (WSS), seamlessly punching through NATs and home routers to service

## 🛡️ Anti-Cheat & HA Failover
1. **Active Inference Probe**: Validators and Business APIs no longer trust simple pings. They fire a real 5-token micro-prompt. If the backend fails to respond within 8 seconds, the miner is marked as a "Ghost Script" and banned from routing.
2. **HA Failover**: If a miner drops during a real user request, the Business API silently catches the error and reroutes the traffic to the next available miner in the pool.
3. **Application Ping/Pong**: An internal 30-second heartbeat  to keep WS tunnels alive forever.
4. **Instant Penalty**: If the miner's backend is dead, fake, or times out, it is instantly marked offline. It receives **0 base score** from the Validator and is **banned from the routing pool** in the Business API.


## 📊 Scoring Mechanism
A miner's final score is calculated by weighting two parts: **Base Score** and **Business Score**. 

Final Score = (Base Score × 10%) + (Business Score × 90%)`
### 1. Base Score (Total 10% Weight)
*   **Model Availability (30%):** Checks if the declared model name is in the dynamically updated whitelist.
*   **Availability (40%):** Full points ONLY if the miner successfully completes the Active Inference Probe.
*   **Response Time (20%):** Tiered scoring (<100ms: 100 pts, <500ms: 80 pts, <1000ms: 60 pts, <2000ms: 40 pts, >2000ms: 20 pts).
*   **Historical Uptime (10%):** Calculated based on the success rate of the last 100 probes.
### 2. Business Score (90% Weight)
The Business API logs all real user requests forwarded through the HA load balancer and provides scoring to the Validator:
*   **Model Base Score (Max 20 pts):** Assigned based on the model tier configuration.
*   **Token Contribution Score (Max 70 pts):** 1 point per 10,000 tokens processed, evaluated over a rolling 24-hour window from the  database.



## 🚀 Deployment Guide
**Requires Python 3.10+.**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
### 1. Start Miner
```bash
# Edit configs/miner.env
# Replace Your local MODEL_URL=http://localhost:8000/v1
# Replace Your local MODEL_NAME=qwen3.5:9b
# Replace Your local WALLET_NAME=default
# Replace Your local WALLET_HOTKEY=miner
# Keep other value
python miner.py
```
### 2. Start Validator
```bash
# Edit configs/validator.env
# Replace Your local WALLET_NAME=default
# Replace Your local WALLET_HOTKEY=miner
# Keep other value
python validator.py
```
## 📝 Log Management System
All core components feature an enterprise-grade rolling log system. In addition to console output, logs are automatically persisted to the `logs/` directory:
- **Daily Rotation**: Generates a new file every midnight formatted as `module-YYYYMMDD.

**In the next phase, we will launch the user UI, integrate Tao wallet connectivity, and enable Tao/Alpha deposits and spending.**

<img width="3002" height="1488" alt="image" src="https://github.com/user-attachments/assets/401eb4b2-fa60-4767-b593-8675d00bc8f4" />
