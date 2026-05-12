# Voting System Guide

## Overview

The Rich Kids of TAO subnet features a decentralized voting system that allows SN110 Alpha holders to vote on subnet weights using their coldkey signatures. The more Alpha you hold, the greater your voting power.

## Architecture

1. **Voters** submit signed votes via CLI
2. **API** verifies signatures and stores votes
3. **Validators** fetch aggregated weights from API
4. **Weights** are calculated by averaging all votes

## Quick Start

### 1. Submit a Vote

```bash
cd rkt-subnet
pip install -e .
python vote.py --wallet.name YOUR_WALLET
```

Uses your bittensor wallet coldkey (same as `btcli`)

### 2. View Results

Check current weights:
```bash
curl https://richkidsoftao.com/api/subnets
```

View all votes:
```bash
curl https://richkidsoftao.com/api/votes
```

## How Voting Works

1. **Sign Message**: Your coldkey signs a message containing your vote
2. **Verify Signature**: API verifies you control the coldkey
3. **Store Vote**: Your vote is stored (overwrites previous vote)
4. **Calculate Weights**: All votes are averaged to determine final weights

## Vote Format

Subnet weights must sum to 1.0 in JSON format:
```json
{"10":0.2,"51":0.15,"64":0.15,"62":0.2,"4":0.1,"8":0.1,"13":0.1}
```

## Security

- **Signature Verification**: Uses Ed25519 signatures via Polkadot libraries
- **Message Integrity**: Message must match `{coldkey, subnets}` format
- **Voting Cooldown**: Can only vote once per 1440 minutes (24 hours) per coldkey
- **Transparent**: All votes are viewable via `/api/votes`

## Testing

Create a test wallet:
```bash
btcli wallet create --wallet.name test-voter
```

Then vote with it:
```bash
python vote.py --wallet.name test-voter
```

## Future Enhancements

- Weight votes by SN110 Alpha balance
- Vote decay over time
- Cooldown periods
- Vote history tracking

