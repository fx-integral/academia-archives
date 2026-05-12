<div align="center">

# Wahooτ

</div>

<div align="center">

*We reduce life to a button. Prediction Markets are THE future.*

**Earn TAO rewards by trading on prediction markets. No code required.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

</div>

---

![Wahoot Banner](/images/wahoot-banner.jpg)

## What Makes This Special?

Picture this: You're already trading on prediction markets, making calls on whether your favorite team will win or if that political candidate will pull through. Now imagine getting **paid in TAO/alpha** just for doing what you're already doing. That's **Wahooτ** – we took the prediction markets you love and added a Bittensor rewards layer on top.

Just trade, perform well, and watch the rewards come in.

### What is Wahooτ?

Wahooτ is where the action happens. You're trading on what people *actually* think is going to happen – in real-time. Politics, sports, economics, you name it. It's like having a front-row seat to the world's collective gut feeling, and you can bet on it.

**Here's what makes it awesome:**
- **Live markets** on literally everything – from "Will it rain tomorrow?" to "Will Bitcoin hit $100k?"
- **Dead simple Yes/No bets** – no complex derivatives, no confusing options
- **Odds that move in real-time** – watch the market react to news as it breaks
- **Trade from anywhere** – just open your browser and go
- **Want to automate?** Full API access for the power users

### How It All Works Together

Okay, here's the deal: You don't need to understand blockchain, APIs, or any of that stuff. But if you're the curious type (we like you), here's what happens behind the curtain:

1. **You register** – Link your Bittensor wallet to Wahooτ (seriously, 2 minutes max)
2. **You trade** – Do your thing on Wahooτ like you always do
3. **We track** – Our validators peek at your performance through the Wahooτ API (don't worry, it's all public data)
4. **You get scored** – Based on how much you trade, how much you profit, and how often you're right
5. **You earn TAO/alpha** – Rewards hit your miner wallet based on your actual trading chops

**The formula is simple:** Better trades = More rewards. More trades = More rewards. It's all about your real performance, not some abstract code test.

### Why Wahooτ is Revolutionary for Bittensor

Let's be real – most Bittensor subnets read like a computer science textbook. You need to know Python, understand neural networks, and probably have a server running 24/7. **We said "nah" to all of that.**

Here's what makes us different:

- ✅ **Literally zero coding** – If you can click "Yes" or "No" on a prediction, you're qualified
- ✅ **Real money, real performance** – We reward actual trading skills, not your ability to write a script. Got previously experience with automated trading? Then that's only an advantage over your competetition.
- ✅ **Built on something that works** – Wahooτ is already live and thriving. We just added the rewards layer
- ✅ **Nothing to hide** – Your performance is public, so you can see exactly why you're earning what you're earning

---

## Start Mining Today

Check out our detailed [mining guide](miners.md) to start earning alpha based on your predictions!

---

## Running a Validator

Check out our detailed [validator guide](validators.md) if you're a validator!

---

### Troubleshooting

**Issue: Dependencies fail to install**

- Make sure you're in a virtual environment
- Try running with elevated privileges: `sudo wahoo-validator-init`

**Issue: Database errors**

- Check that SQLite is installed: `sqlite3 --version`
- Verify database path permissions
- Try deleting the database file and re-running initialization

**Issue: Import errors**

- Ensure the package is installed in editable mode: `uv pip install -e .`
- Verify your virtual environment is activated
- Check that all dependencies are installed: `uv pip list`

**Issue: Alembic migration errors**

- Ensure you're running from the project root directory
- Check that `wahoo/validator/database/alembic.ini` exists
- Try manually running: `cd wahoo/validator/database && alembic upgrade head`

#### Database

The validator uses SQLite for local data persistence. Database auto-initializes on first run with schema creation. Features include:
- Caches validation data from Wahooτ API (reduces API calls)
- Stores EMA scores for persistence across restarts
- Automatic cleanup of old cache entries (7 days default)
- WAL mode enabled for better write concurrency

Default location: `~/.wahoo/validator.db`. Set `VALIDATOR_DB_PATH` environment variable for custom location.


#### Database Query Tool

The validator includes a built-in database query tool for inspecting your validator's database:

**Usage:**

```bash
# After installation, the tool is available as:
wahoo-db-query <command> [options]

# Or directly via Python:
python -m wahoo.entrypoints.db_query <command> [options]
```

**Available Commands:**

```bash
# Show database statistics
wahoo-db-query stats

# List all registered miners
wahoo-db-query miners

# Show latest EMA scores (default: 20 most recent)
wahoo-db-query scores
wahoo-db-query scores --limit 50

# Show latest score for each miner
wahoo-db-query latest-scores

# Show performance snapshots
wahoo-db-query performance
wahoo-db-query performance --hotkey <hotkey> --limit 20

# Show detailed info for a specific miner
wahoo-db-query miner <hotkey>
```

**Examples:**

```bash
# Quick database health check
wahoo-db-query stats

# See which miners are being actively scored
wahoo-db-query latest-scores

# Check a specific miner's trading performance
wahoo-db-query miner miner_hotkey_here

# View recent scoring activity
wahoo-db-query scores --limit 100
```

The tool automatically finds your validator database using the same logic as the validator itself (respects  Database file path (each validator gets their own). environment variable or uses the default location).

#### Development Setup

For development work, install with dev dependencies:

```bash
# With uv
uv pip install -e ".[dev]"
```

---

## 📚 Need More Info?

Want to dive deeper? Here's where to go:

- **Ready to trade?** Head to [wahoopredict.com](https://wahoopredict.com/?utm_source=subnet) and see what's happening
- **Want to understand Wahooτ better?** The [Wahooτ docs](https://wahoopredict.gitbook.io/wahoopredict-docs/getting-started/what-is-wahoopredict) will fill you in
- **Bittensor Networks**: Learn about mainnet, testnet, and network endpoints at [Bittensor Networks Documentation](https://docs.learnbittensor.org/concepts/bittensor-networks)
- **Bittensor CLI**: Full reference at [BTCLI Documentation](https://docs.learnbittensor.org/btcli/btcli)
- **New to Bittensor?** The [official Bittensor docs](https://docs.bittensor.com) are your friend

Still have questions? That's cool. We're here to help make this as simple as possible. Assistance will be provided via our subnet channel on the [official Bittensor Discord](https://discord.gg/bittensor)

Interested in our plans for the future? Look towards our [roadmap](/roadmap.md) for our current plans heading forwards.

---

## 📄 License

MIT License - see LICENSE file for details.

---