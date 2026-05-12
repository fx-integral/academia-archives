# Running Miner on Mainnet

Your incentive mechanisms running on the mainnet are open to anyone. They emit real TAO. Creating these mechanisms incur a `lock_cost` in TAO.

**DANGER**
- Do not expose your private keys.
- Only use your testnet wallet.
- Do not reuse the password of your mainnet wallet.
- Make sure your incentive mechanism is resistant to abuse. 

## Prerequisites

Before proceeding further, make sure that you have installed Bittensor. See the below instructions:

- [Install `bittensor`](https://github.com/opentensor/bittensor#install).

After installing `bittensor`, proceed as below:

## Server Requirements

To successfully run this node, your server environment must meet the following hardware and network requirements:

- **GPU Requirement:**  
  The server **must include an NVIDIA GPU** with CUDA support.  
  This is required for computation, model inference, and network validation tasks.

- **Network and Ports:**  
  Ensure that **TCP ports 8000–8010** are **open and accessible** from the public internet.  
  These ports are used for peer-to-peer communication and validator-to-miner interactions.

> 💡 Tip: You can verify your port configuration using tools like `nmap` or `netcat`.


## Steps

## 1. Install your internet-of-intelligence

**NOTE: Skip this step if** you already did this during local testing and development.

In your project directory:

```bash
git clone https://github.com/subnet108/internet-of-intelligence
```

Next, `cd` into `internet-of-intelligence` repo directory:

```bash
cd internet-of-intelligence
```

Install the internet-of-intelligence package:

```bash
pip install -e . # Install your internet-of-intelligence package
```
or 
```bash
pip install -r requirements.txt # Install your internet-of-intelligence package
```

## 2. Create wallets 

Create a coldkey and hotkey for the subnet miner wallet:
```bash
btcli wallet new_coldkey --wallet.name miner
```

and

```bash
btcli wallet new_hotkey --wallet.name miner --wallet.hotkey default
```

## 3. Register keys 

Register your miner key to the subnet:

```bash
btcli subnets register --netuid 108 --subtensor.network finney --wallet.name miner --wallet.hotkey default
```

Follow the below prompts:

```bash
>> Enter netuid [108] : # Enter netuid 108 to specify the subnet you just created.
>> Continue Registration?
  hotkey:     ...
  coldkey:    ...
  network:    finney [y/n]: # Select yes (y)
>> ✅ Registered
```

## 4. Check that your keys have been registered

Check that your subnet miner has been registered:

```bash
btcli wallet overview --wallet.name miner 
```

The output will be similar to the below:

```bash
Subnet: 108                                                                                                                                                                
COLDKEY  HOTKEY   UID  ACTIVE  STAKE(τ)     RANK    TRUST  CONSENSUS  INCENTIVE  DIVIDENDS  EMISSION(ρ)   VTRUST  VPERMIT  UPDATED  AXON  HOTKEY_SS58                    
miner    default  1      True   0.00000  0.00000  0.00000    0.00000    0.00000    0.00000            0  0.00000                14  none  5GTFrsEQfvTsh3WjiEVFeKzFTc2xcf…
1        1        2            τ0.00000  0.00000  0.00000    0.00000    0.00000    0.00000           ρ0  0.00000                                                         
                                                                          Wallet balance: τ0.0   
```

## 5. Run subnet miner

Run the subnet miner:

```bash
python -m neurons.miner.src.miner --netuid 108 --wallet.name miner --wallet.hotkey default --logging.debug
```

You will see the below terminal output:

```bash
>> 2023-08-08 16:58:11.223 |       INFO       | Running miner for subnet: 108 on network: wss://entrypoint-finney.opentensor.ai:443 with config: ...
```

## 6. Run docker
```bash
docker --version
```
If did not correctly install, follow this link

```bash
cd neurons/miner && docker-compose up -d 
```

## 7. Stopping your nodes

To stop your nodes, press CTRL + C in the terminal where the nodes are running.

---