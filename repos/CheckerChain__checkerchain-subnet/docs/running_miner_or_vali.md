# Running Miner/Validator on CheckerChain Subnet

## Prerequisites

Before proceeding further, make sure that you have installed Bittensor. See the below instructions:

- [Install `bittensor`](https://github.com/opentensor/bittensor#install).

After installing `bittensor`, proceed as below:

## 1. Install Checker Chain Subnet

`cd` into your project directory and clone the checkerchain-subnet repo:

```bash
git clone https://github.com/CheckerChain/checkerchain-subnet.git
```

Next, `cd` into checkerchain-subnet repo directory:

```bash
cd checkerchain-subnet # Enter the
```

### Manual steps:

#### Create Python Virtual Environment:

```bash
python -m venv .venv

```

#### Activate venv:

```bash
source .venv/bin/activate  #use wsl2 for windows
```

#### Install the checkerchain-subnet package:

```bash
python -m pip install -e .
```

## Using Scripts (It will delete checker_db.db file):

#### Validator

```bash
chmod +x scripts/setup_vali.sh
./scripts/setup_vali.sh
```

#### Miner

```bash
chmod +x scripts/setup_miner.sh
./scripts/setup_miner.sh
```

#### Activate Venv

```bash
source .venv/bin/activate
```

## 2. Create wallets

Create wallets subnet validator or subnet miner.

This step creates local coldkey and hotkey pairs for either subnet validator or subnet miner.
The validator or miner will be registered to the subnet

Create a coldkey and hotkey for miner wallet:

```bash
btcli wallet new_coldkey --wallet.name miner
```

and

```bash
btcli wallet new_hotkey --wallet.name miner --wallet.hotkey default
```

Create a coldkey and hotkey for validator wallet:

```bash
btcli wallet new_coldkey --wallet.name validator
```

and

```bash
btcli wallet new_hotkey --wallet.name validator --wallet.hotkey default
```

## 3. (Optional) Get faucet tokens

Faucet is disabled on the testnet. Hence, if you don't have sufficient faucet tokens, ask the [Bittensor Discord community](https://discord.com/channels/799672011265015819/830068283314929684) for faucet tokens.

## 4. Register keys

**_Testnet NETUID: `315`_** \
**_Mainnet NETUID: `87`_**

#### Registering Miner

This step registers subnet miner key to the subnet.

Copy `.env.example` to `.env` and update your `OPENAI_API_KEY`

Register your miner key to the subnet:\
\***\*Add `--subtensor.network test` for testnet\*\***

```bash
btcli subnet register --netuid 87 --wallet.name miner --wallet.hotkey default
```

Follow the below prompts:

```bash
>> Enter netuid [1] (1): # Enter netuid depending upon the network you want to register for
>> Continue Registration?
  hotkey:     ...
  coldkey:    ...
  network:    finney [y/n]: # Select yes (y)
>> ✅ Registered
```

#### Registering Validator

This step registers subnet validator key to the subnet.

Register your validator key to the subnet:\
\***\*Add `--subtensor.network test` for testnet\*\***

```bash
btcli subnet register --netuid 87 --wallet.name validator --wallet.hotkey default
```

Follow the prompts:

```bash
>> Enter netuid [1] (1): # Enter netuid depending upon the network you want to register for
>> Continue Registration?
  hotkey:     ...
  coldkey:    ...
  network:    finney [y/n]: # Select yes (y)
>> ✅ Registered
```

## 5. Check that your keys have been registered

\***\*Add `--subtensor.network test` for testnet\*\***

This step returns information about your registered keys.

Check that your validator key has been registered:

```bash
btcli wallet overview --wallet.name validator
```

The above command will display the below:

```bash
Subnet: 315
COLDKEY  HOTKEY   UID  ACTIVE  STAKE(τ)     RANK    TRUST  CONSENSUS  INCENTIVE  DIVIDENDS  EMISSION(ρ)   VTRUST  VPERMIT  UPDATED  AXON  HOTKEY_SS58
miner    default  0      True   0.00000  0.00000  0.00000    0.00000    0.00000    0.00000            0  0.00000                14  none  5GTFrsEQfvTsh3WjiEVFeKzFTc2xcf…
1        1        2            τ0.00000  0.00000  0.00000    0.00000    0.00000    0.00000           ρ0  0.00000
                                                                          Wallet balance: τ0.0
```

Check that your miner has been registered:

```bash
btcli wallet overview --wallet.name miner
```

The above command will display the below:

```bash
Subnet: 315
COLDKEY  HOTKEY   UID  ACTIVE  STAKE(τ)     RANK    TRUST  CONSENSUS  INCENTIVE  DIVIDENDS  EMISSION(ρ)   VTRUST  VPERMIT  UPDATED  AXON  HOTKEY_SS58
miner    default  1      True   0.00000  0.00000  0.00000    0.00000    0.00000    0.00000            0  0.00000                14  none  5GTFrsEQfvTsh3WjiEVFeKzFTc2xcf…
1        1        2            τ0.00000  0.00000  0.00000    0.00000    0.00000    0.00000           ρ0  0.00000
                                                                          Wallet balance: τ0.0
```

## 6. Run subnet miner Or subnet validator

Run the subnet miner:

```bash
python neurons/miner.py --netuid 87 --wallet.name miner --wallet.hotkey default --logging.debug
```

Next, run the subnet validator:

```bash
python neurons/validator.py --netuid 87 --wallet.name validator --wallet.hotkey default --logging.debug
```

## 7. Stopping your nodes

To stop your nodes, press CTRL + C in the terminal where the nodes are running.

Sure! Here's a more detailed and well-formatted section for a **GitHub `README.md`** to help miners troubleshoot and ensure their setup is correct:
