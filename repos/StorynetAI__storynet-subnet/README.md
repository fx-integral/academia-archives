# StoryNet Subnet (SN92)

> **Decentralized AI Story Generation Network on Bittensor**

## What is StoryNet?

StoryNet is a Bittensor subnet dedicated to **AI-powered interactive story generation**. Miners compete to create high-quality narrative content, and validators score their outputs using a multi-dimensional evaluation system.

**Subnet ID:** 92 (Mainnet)

## Why Join StoryNet?

- **Earn TAO** by generating creative story content
- **AI-Powered Scoring** ensures fair and objective evaluation
- **Anti-Gaming Mechanisms** protect honest miners from copycats
- **Growing Demand** for interactive narrative content in gaming and entertainment

## For Miners

### Requirements

- Python 3.9+
- Bittensor wallet with registration fee
- API access to an LLM provider (OpenAI, Zhipu, Gemini, etc.)

### Quick Start

```bash
# Clone repository
git clone https://github.com/StorynetAI/storynet-subnet.git
cd storynet-subnet

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp config/generator_config.yaml.example config/generator_config.yaml
export OPENAI_API_KEY=sk-...  # or ZHIPU_API_KEY

# Register to subnet
btcli subnet register --netuid 92 --wallet.name miner --wallet.hotkey default

# Start mining
python neurons/miner.py \
    --netuid 92 \
    --wallet.name miner \
    --wallet.hotkey default \
    --subtensor.network finney \
    --axon.port 8091 \
    --logging.info
```

### Cloud Deployment

If running on a cloud server, specify your public IP:

```bash
python neurons/miner.py \
    --netuid 92 \
    --wallet.name miner \
    --wallet.hotkey default \
    --axon.port 8091 \
    --axon.external_ip YOUR_PUBLIC_IP \
    --axon.external_port 8091 \
    --logging.info
```

### 🐳 Run Miner with Docker + Watchtower
This guide shows how to deploy the miner using Docker Compose, with automatic updates via Watchtower. 
The miner will run on port 9292, and requires your Bittensor wallet files to be located in ~/.bittensor.

#### 🛠️ Setup Instructions
```bash
# Setup .env File
cd Docker/miner
cp .env_example .env
nano .env # or use any editor: vim, code, etc.
```

#### 🛠️ Edit the following required fields:
```env
# Setup your env
WALLET_NAME=default
HOTKEY_NAME=default
# Choose ONE of the following:
ZHIPU_API_KEY=your_zhipu_api_key_here
# OR
OPENAI_API_KEY=sk-your-openai-api-key-here
```
🔐 Never commit .env to version control. It should be in your .gitignore.

#### 🚀 Deploy with Docker Compose

```bash
docker compose down && docker compose pull && docker compose up -d && docker compose logs -f
```

## For Validators

### Requirements

- Python 3.9+
- Bittensor wallet with sufficient stake
- (Optional) API key for AI-based narrative scoring

### Quick Start

```bash
# Clone and install
git clone https://github.com/StorynetAI/storynet-subnet.git
cd storynet-subnet
pip install -r requirements.txt

# Configure narrative evaluation (optional, enhances scoring)
cp config/narrative_eval.yaml.example config/narrative_eval.yaml

# Register and start
btcli subnet register --netuid 92 --wallet.name validator --wallet.hotkey default

python neurons/validator.py \
    --netuid 92 \
    --wallet.name validator \
    --wallet.hotkey default \
    --subtensor.network finney \
    --logging.info
```
### 🐳 Run Validator with Docker + Watchtower
This guide shows how to deploy the validator using Docker Compose, with automatic updates via Watchtower. 
The validator will run on port 19292, and requires your Bittensor wallet files to be located in ~/.bittensor.

#### 🛠️ Setup Instructions
```bash
# Setup .env File
cd Docker/validator
cp .env_example .env
nano .env # or use any editor: vim, code, etc.
```

#### 🛠️ Edit the following required fields:
```env
# setup your env
WALLET_NAME=default
HOTKEY_NAME=default
# Choose ONE of the following:
ZHIPU_API_KEY=your_zhipu_api_key_here
# OR
OPENAI_API_KEY=sk-your-openai-api-key-here
```
🔐 Never commit .env to version control. It should be in your .gitignore.

#### 🚀 Deploy with Docker Compose

```bash
docker compose down && docker compose pull && docker compose up -d && docker compose logs -f
```

## Scoring System

Miners are evaluated on a **100-point scale**:

| Component | Points | What It Measures |
|-----------|--------|------------------|
| Technical | 20 | Valid JSON, schema compliance, response time |
| Structure | 30 | Story arc coherence, chapter progression |
| Content | 20 | Relevance, fluency, originality |
| Narrative | 30 | AI-evaluated creative quality |

### Anti-Cheating

- **Plagiarism Detection**: Responses too similar to history are penalized
- **Blacklist System**: Known bad actors are blocked
- **Originality Scoring**: Rewards unique, creative content

## Generation Pipeline

StoryNet uses a 4-stage story generation pipeline:

1. **Blueprint** → Story premise, genre, setting
2. **Characters** → Cast of characters with backgrounds
3. **Story Arc** → Chapter outlines and plot progression
4. **Chapters** → Full chapter content with choices

## Monitoring

```bash
# Check subnet status
btcli subnet list --netuid 92

# Check your miner/validator status
btcli wallet overview --wallet.name miner

# Check current weights
btcli weights --netuid 92
```

## Resources

- [Bittensor Docs](https://docs.bittensor.com)
- [Subnet Registration Guide](https://docs.bittensor.com/subnets/register-validate-mine)

## License

MIT License