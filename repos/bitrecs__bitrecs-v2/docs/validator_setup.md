# V2 Validator Setup

- We recommend Ubuntu 24+ LTS
- V2 validators do not require public IPs or open ports

# Update & Reboot
```
sudo apt-get update
sudo apt-get upgrade
```

# Install Docker

```sudo apt install apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update

apt-cache policy docker-ce

sudo apt install docker-ce

sudo systemctl status docker
```

# Install UV

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

# Setup Working Directory
```
mkdir bitrecs
cd bitrecs

Please ensure the folder is named bitrecs as docker compose expects ~/bitrecs
```

# Setup Wallet
```
uv init
uv pip install bittensor-cli
uv run btcli w regen-coldkeypub --ss58 COLDKEY_ADDR
uv run btcli w regen-hotkey
```


# Pull Images
```
docker pull ghcr.io/bitrecs/bitrecs-v2:main
docker pull ghcr.io/bitrecs/bitrecs-evals:main
```

# Setup Env

touch .env

```
DEBUG=False

NETUID=296
BITRECS_PLATFORM_URL=
BITRECS_PLATFORM_API_KEY=
SUBTENSOR_NETWORK=test
SUBTENSOR_ADDRESS=

MODE="validator"
SCREENER_NAME=
SCREENER_PASSWORD=
SEND_HEARTBEAT_INTERVAL_SECONDS=20
SET_WEIGHTS_INTERVAL_SECONDS=300

VALIDATOR_WALLET_NAME=default
VALIDATOR_HOTKEY_NAME=default

CHECK_RUNNING_AGENTS_INTERVAL_SECONDS=60
CHECK_PENDING_EVALUATIONS_INTERVAL_SECONDS=30
CHECK_AGENT_UPLOAD_RATE_LIMIT_INTERVAL_SECONDS=600
R2_SYNC_INTERVAL_SECONDS=900
REQUEST_EVALUATION_INTERVAL_SECONDS=45
SIMULATE_EVALUATION_RUNS=False
SIMULATE_EVALUATION_RUN_MAX_TIME_PER_STAGE_SECONDS=3

OPENROUTER_API_KEY=
CHUTES_API_KEY=

AGORA_URL=
AGORA_API_KEY=

```

# Docker Compose 
 
Validator Docker Compose: [docker-compose-prod.yml](../validator/docker-compose-prod.yml) 

```
copy .yml file into ~/bitrecs:

curl -L -o docker-compose-prod.yml "https://raw.githubusercontent.com/bitrecs/bitrecs-v2/refs/heads/main/validator/docker-compose-prod.yml"

docker compose -f docker-compose-prod.yml up -d
```

# Logs

```
docker compose -f docker-compose-prod.yml logs --tail 10 --follow validator
```

# Watchtower

Watcher should automatically be setup, check docker ps to ensure both containers (bitrecs validator and watchtower) are running. During evaluation the validator will spawn a child container containing [bitrecs-evals](https://github.com/bitrecs/bitrecs-evals)