# Rich Kids of TAO

It was the ultimate proof-of-wealth Bittensor subnet, then turned out to become a next-level of Miner Appreciation subnet.

## What is Rich Kids of TAO?

Rich Kids of TAO is a Bittensor subnet that distributes rewards to miners based on their emissions across subnets chosen by community vote. Unlike previous "Miner Appreciation" subnets, this system allows existing miners to vote on which subnets should be weighted for reward distribution, making the process more adaptive to the ecosystem.

## How it Works

- **Miners**: Simply register to the subnet - no code to run
- **Validators**: Check miners' emissions across voted subnets and distribute rewards accordingly
- **Rewards**: Based on total emission value across voted subnets (emission × subnet price × subnet weight)

## For Miners

1. Register your hotkey to the subnet:
```bash
btcli subnet register --netuid 110 --wallet.name YOUR_WALLET --wallet.hotkey YOUR_HOTKEY
```

2. That's it! Your rewards are based on your emissions across the voted subnets.

## For Voters (Alpha Holders)

Vote on which subnets should receive more weight in the miner appreciation system:

```bash
python vote.py --wallet.name YOUR_WALLET
```

You'll be prompted to enter subnet weights as JSON that sum to 1.0. Example:
```json
{"10":0.2,"51":0.15,"64":0.15,"62":0.2,"4":0.1,"8":0.1,"13":0.1}
```

## For Validators

1. Install dependencies:
```bash
pip install -e .
```

2. Install PM2:
```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

Restart your terminal, and:

```
nvm i 21 && npm i pm2 -g
```

3. Run the validator:
```bash
pm2 start ./autoupdater.sh --name "rich-kids-autoupdater" -- 110 YOUR_WALLET YOUR_HOTKEY
```

The code is super lightweight. So a very small machine can do the job. The following config is usually one of the cheapest options in the clouds. You can make it even smaller, up to you.

Richie's suggestion would be:
- 2 vCPU
- 8GB RAM
- 50GB Disk
- Ubuntu 22.04 LTS
- Python 3.12
- No GPUs

## Testing

Test the emission checking logic:
```bash
python test_emission.py
```

## Emission Calculation

Your score is based on:
- **Miner Emissions**: Total miner emission rate in each voted subnet
- **Alpha Price**: The alpha price of the subnet
- **Voted subnet Weights**: Community-voted weights for each subnet

The validator calculates: `total_value = sum(emission × price × weight)` across all voted subnets and distributes rewards proportionally.

---

*Appreciate the miners, reward the ecosystem.* 🚀
