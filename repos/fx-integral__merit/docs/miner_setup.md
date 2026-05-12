# Merit Subnet - Miner Setup Guide

---

## 1. Install Required System Packages

Ensure your system has the necessary Python environment.

```bash
sudo apt update
sudo apt -y install python3-venv python3-pip python-is-python3
```

If **not using Docker containers**, you must also install `ntpsec` to maintain accurate system time:

```bash
sudo apt -y install ntpsec
```

---

## 2. Clone the Merit Repository

```bash
git clone https://github.com/fx-integral/merit.git
cd merit
```

---

## 3. Create and Activate Python Virtual Environment

```bash
python -m venv venv
source venv/bin/activate
```

---

## 4. Install Required Python Packages

Using [uv](https://github.com/astral-sh/uv) (a fast modern package manager):

```bash
pip install uv
uv pip install -r requirements.txt
```

---

## 5. Running the Miner

Use the following command structure to launch your miner:

```bash
python -m merit.scripts.run_miner \
  --subtensor.network finney \
  --wallet.name {wallet_name} \
  --wallet.hotkey {hotkey_name} \
  --netuid 73 \
  --axon.port {port_number} \
  --logging.debug
```

### Example:

```bash
python -m merit.scripts.run_miner \
  --subtensor.network finney \
  --wallet.name mywallet \
  --wallet.hotkey miner1 \
  --netuid 73 \
  --axon.port 8091 \
  --logging.debug
```

---

# End of Document
