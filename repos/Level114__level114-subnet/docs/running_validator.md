# Level114 Subnet Validator Guide

This guide covers how to run the Level114 subnet validator with the integrated comprehensive scoring system.

## 🎯 Overview

The Level114 validator uses an advanced scoring system that evaluates Minecraft servers based on:

- **Infrastructure Performance** (40%): TPS, latency, memory usage
- **Participation Quality** (35%): Plugin compliance, player count, registration
- **Reliability Metrics** (25%): Uptime stability, TPS consistency, recovery time

## 📋 Prerequisites

1. **Python 3.8+** with pip installed
2. **Bittensor wallet** set up and registered on subnet 114
3. **Collector API access** - Contact Level114 team for API key
4. **System Requirements**: 4GB RAM, 2 CPU cores, 50GB storage minimum

## 🚀 Quick Start

### 1. Run with Minimum Configuration

```bash
./scripts/run_validator.sh \
  --collector.url http://collector.level114.io:3000 \
  --collector.api_key vk_your_api_key_here \
  --wallet.name your_wallet_name \
  --wallet.hotkey your_validator_hotkey
```

### 2. Production Configuration

```bash
./scripts/run_validator.sh \
  --netuid 114 \
  --network finney \
  --wallet.name production_wallet \
  --wallet.hotkey validator_hotkey \
  --collector.url http://collector.level114.io:3000 \
  --collector.api_key vk_prod_your_api_key_here \
  --collector.timeout 30.0 \
  --collector.reports_limit 50 \
  --validator.weight_update_interval 300 \
  --validator.validation_interval 1440 \
  --log_level INFO
```

## ⚙️ Configuration Options

### Core Settings
- `--netuid 114` - Level114 subnet ID
- `--network finney` - Bittensor network (finney/test/local)
- `--wallet.name NAME` - Your wallet name
- `--wallet.hotkey HOTKEY` - Your validator hotkey

### Collector API Settings
- `--collector.url URL` - **Required** - Collector API base URL
- `--collector.api_key KEY` - **Required** - Your validator API key
- `--collector.timeout SECONDS` - API timeout (default: 10.0)
- `--collector.reports_limit N` - Max reports per query (default: 25)

### Validator Scoring Settings
- `--validator.weight_update_interval SEC` - Weight update frequency (default: 300 = 5 minutes)
- `--validator.validation_interval SEC` - Validation cycle interval (default: 1440 seconds / 24 minutes, minimum enforced to avoid rate limits)

### Logging
- `--log_level LEVEL` - DEBUG, INFO, WARNING, ERROR (default: INFO)

## 📊 Understanding the Scoring System

### Score Ranges
| Score | Range | Classification | Weight Multiplier |
|-------|-------|---------------|-------------------|
| 850-1000 | Excellent | Maximum rewards | 0.85-1.00 |
| 650-849 | Good | High rewards | 0.65-0.84 |
| 400-649 | Average | Medium rewards | 0.40-0.64 |
| 300-399 | Poor | Low rewards | 0.30-0.39 |
| 0-299 | Critical | Minimal rewards | 0.00-0.29 |

### Component Breakdown

**Infrastructure (40% weight):**
- TPS Performance: `actual_tps / 20.0` (capped at 20 TPS)
- HTTP Latency: `1.0 - (latency_seconds / 1.0)` (capped at 1s)
- Memory Headroom: `free_memory / total_memory`

**Participation (35% weight):**
- Plugin Compliance: Required plugins present (Level114)
- Player Activity: `active_players / 200` (capped at 200 players)
- Registration Status: Server properly registered with validator

**Reliability (25% weight):**
- Uptime Consistency: Monotonic uptime increases without resets
- TPS Stability: Low coefficient of variation in TPS measurements
- Recovery Speed: How quickly server recovers from issues

## 🔍 Monitoring Your Validator

### Log Messages to Watch For

**Successful Initialization:**
```
✅ Level114 scoring system initialized successfully
🌐 Collector API: collector.level114.io
⚖️ Weight update interval: 1200s
```

**Successful Validation Cycles:**
```
🔄 Starting Level114 validation cycle...
✅ Validation cycle complete: 5 servers processed, 5 scores updated, 0 errors, weights updated: true, cycle time: 2.1s
```

**Weight Updates:**
```
🏋️ Updating blockchain weights...
✅ Weights updated for 5 miners (total weight: 1.000)
```

**Status Summaries (every 10 cycles):**
```
📊 LEVEL114 VALIDATOR STATUS SUMMARY
🔄 Cycles completed: 10
⚖️ Last weights update: Fri Sep 19 16:00:00 2025
🗂️ Cached scores: 5
📇 Cached mappings: 5
```

### Warning Signs

❌ **Configuration Issues:**
```
❌ --collector.url is required
❌ --collector.api_key is required
```

⚠️ **API Problems:**
```
⚠️ Collector API status 401 (check API key)
⚠️ Collector API status 500 (server issues)
```

🔄 **Scoring Issues:**
```
❌ Error in validation cycle: [details]
⚠️ Using basic fallback validation
⚠️ Collector returned no reports for server ...; downgrading score to 0
⚠️ Collector reports for server ... are older than 6h; downgrading score to 0
```

## 🧠 Data Handling

- **Collector Center API** is the single source of truth for server reports and mappings.
- **Runtime caches** store recent scores and hotkey→server mappings in memory only.
- **Historical context** is pulled from the last 25 reports per server on every scoring cycle.
- **Cache resets** happen automatically when the process restarts—no manual cleanup required.

## 🛠️ Troubleshooting

### Common Issues

**1. Import Errors**
```bash
# Test your installation
python3 test_integrated_validator.py
```

**2. API Authentication**
```bash
# Test API access manually
curl -H "Authorization: Bearer your_api_key" \
  http://collector.level114.io:3000/validators/health
```

**3. Weight Setting Issues**
- Ensure your wallet has sufficient TAO for transaction fees
- Check you're registered on the correct subnet (netuid 114)
- Verify your hotkey has validator permissions

### Debug Mode

Enable detailed logging:
```bash
./scripts/run_validator.sh \
  --log_level DEBUG \
  [... other args ...]
```

### Recovery

**Refresh caches:**
```bash
# Restart validator to clear in-memory caches and pull fresh data
pkill -f neurons/validator.py
./scripts/run_validator.sh [...]
```

**Force immediate weight update:** Weight commits now run every 20 minutes per policy. Restart the validator to trigger the next scheduled update attempt if you need it sooner.

## 🔧 Advanced Configuration

### Environment Variables

Set persistent configuration:
```bash
export LEVEL114_COLLECTOR_URL="http://collector.level114.io:3000"
export LEVEL114_API_KEY="your_api_key_here"
export LEVEL114_WALLET_NAME="your_wallet"
export LEVEL114_WALLET_HOTKEY="your_hotkey"
```

### Custom Scoring Parameters

The validator uses these constants (from `level114/validator/mechanisms/minecraft/constants.py`):

```python
IDEAL_TPS = 20.0          # Target TPS for perfect score
MAX_LATENCY_S = 1.0       # Maximum acceptable latency
MAX_PLAYERS_WEIGHT = 200  # Player count cap for scoring
REQUIRED_PLUGINS = {"Level114"}
```

### Performance Tuning

**Standard cadence (minimum allowed):**
```bash
  --validator.validation_interval 1440    # Check every 24 minutes
--validator.weight_update_interval 300 # Update weights every 5min
```

**Conservative validation:**
```bash
  --validator.validation_interval 1440    # Check every 24 minutes
--validator.weight_update_interval 600 # Update weights every 10min
```

## 📞 Support

- **Discord**: Level114 Community Server
- **GitHub**: [Level114/level114-subnet](https://github.com/Level114/level114-subnet)
- **Issues**: Use GitHub Issues for bugs and feature requests

## 📈 Performance Expectations

A well-tuned validator should achieve:

- **Validation cycles**: default 24 minutes between cycles
- **Weight updates**: Every 5 minutes
- **API latency**: <500ms average
- **Storage growth**: ~1MB per day
- **Memory usage**: 200-500MB
- **CPU usage**: 5-15% average

## 🎉 Success Indicators

Your validator is working well when you see:

✅ Consistent validation cycles with 0 errors  
✅ Regular weight updates every 20 minutes  
✅ Growing number of cached scores  
✅ Stable API connectivity  
✅ Collector history available for each active miner  
✅ Balanced score distribution across miners  

**The Level114 validator will now automatically reward high-performing Minecraft servers and penalize poor performance, creating strong incentives for infrastructure optimization! 🎮⚖️**
