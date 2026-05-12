# Manual testing instructions

This doc details how to test the federated stack in different modes.

## Dependency setup

Clone the repo and set it to the right branch:

```bash
BRANCH='development'
cd
git clone https://github.com/taofu-labs/tpn-subnet.git
cd tpn-subnet/federated-container
git checkout "$BRANCH"

# Linux version
sudo apt update && sudo apt install -y wireguard wireguard-tools iproute2 dnsutils iputils-ping iptables procps resolvconf

# Mac version
brew install wireguard-tools docker-desktop
```

Set up the right `.env` file and make sure to:

- Set `CI_VALIDATOR_IP_OVERRIDES` and `CI_MINER_IP_OVERRIDES` to a comma separated list or single ip of the other boxes
- Set `POSTGRES_HOST=localhost`

```bash
# note that miner is called pool (to prevent confusion to operators in prod)
type=worker|pool|validator
cp ".env.$type.example" ".env"

# Do not add any `MOCK_' values, use the ip addresses of the other boxes where relevand as miners/validators
echo "CI_MODE=true" >> ".env"
nano ".env"
```

Install the dependencies:

```
nvm install && nvm use && npm i
```


## Local mocked

This mode tells the backend to mock responses, this means a lot of logic is not really tested. This is more of a sanity check than a safety measure.

Requirements:

- Two open terminals
- [nvm](https://github.com/nvm-sh/nvm) installed


For local-only mocked testing, you need to set these variables in your `.env`s:

```bash
CI_MODE=true
CI_MOCK_MINING_POOL_RESPONSES=true
CI_MOCK_WORKER_RESPONSES=true
CI_MOCK_WG_CONTAINER=true
MINING_POOL=0
```

Testing flow:

- in one terminal start the stack: `npm run start:worker|miner|validator`
- in the other start the test: `npm run test:worker|miner|validator`


## Live environment

Requirements:

- 3 publically accessible (VPS) servers
- [nvm](https://github.com/nvm-sh/nvm) installed

### Start stack

On each box run the following:

- worker: `docker compose -f docker-compose.yml -f docker-compose.ci.yml down && docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d postgres wireguard`
- miner/validator: `docker compose -f docker-compose.yml -f docker-compose.ci.yml down && docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d postgres` 

Then run the relevant npm start command, note that this will auto-pull changes you push to the branch, and will reload them into the node stack when changes are detected.

```bash
# Ideally start in this order because of the annoucement order
npm run start:validator
npm run start:miner
npm run start:worker
```

### Testing

There are two testing flows:

1. Just wait and look at the logs, this will show you if the daemons are calling and handling requests correctly. Influence this using `DAEMON_INTERVAL_SECONDS`.
2. Run testing suites: `npm run test:worker|miner|validator`
