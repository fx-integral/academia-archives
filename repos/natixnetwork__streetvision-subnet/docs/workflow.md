# Development Workflow

How to set up, run, and contribute to the subnet.

---

## Local setup

Python 3.11 is required (bittensor 9.9.0 constraint). Use pyenv or asdf to manage versions.

```bash
python3.11 -m venv venv
source venv/bin/activate

pip install -e ".[miner]"                                              # miner only
pip install -e ".[validator]"                                          # validator core (no DL, no image processing)
pip install -e ".[validator,validator-image]"                          # validator + cache/augmentation, no DL
pip install -e ".[validator,validator-image,validator-synthetic]"      # full validator
```

---

## Running components

**Miner:**
```bash
bash scripts/start_miner.sh
# or directly:
venv/bin/python neurons/miner.py \
  --neuron.image_detector RoadworkDetector \
  --neuron.image_detector_config roadwork \
  --wallet.name <wallet> --wallet.hotkey <hotkey>
```

**Validator:**
```bash
bash scripts/start_validator.sh
```
This launches three processes:
1. `neurons/validator.py` — main forward loop
2. `natix/validator/scripts/run_cache_updater.py` — downloads parquets from HuggingFace
3. `natix/validator/scripts/run_data_generator.py` — generates synthetic images

**Individual background processes:**
```bash
bash scripts/start_cache_updater.sh
bash scripts/start_synthetic_generator.sh
```

---

## Environment variables

Loaded from `miner.env` or `validator.env`. Key ones:
- `WALLET_NAME`, `WALLET_HOTKEY` — Bittensor wallet
- `NETUID` — subnet UID (e.g., 14 for mainnet)
- `SUBTENSOR_NETWORK` — `finney` (mainnet) or `test` (testnet)
- `PROXY_CLIENT_URL` — URL of the NATIX proxy API
- `HF_TOKEN` — HuggingFace token for dataset downloads
- `WANDB_API_KEY` — Weights & Biases API key (validator only)

---

## Running tests

```bash
pytest tests/                    # all tests
pytest tests/test_forward.py    # specific file
pytest -x                        # stop on first failure
```

Test layout:
- `tests/` — shared/integration tests
- `tests/validator/` — validator-specific tests
- `neurons/unit_tests/` — miner unit tests (separate from main test suite)

---

## Branch model

Two long-lived branches:

- `main` — production-ready code; only updated via reviewed PRs
- `development` — active development; all feature branches and PRs target here

### Feature branches

- Branch from: `development`
- Merge into: `development`
- Naming: `feature/<ticket>/<descriptive-name>` (e.g. `feature/42/add-vit-detector`)

Rebase frequently against `development` to avoid large conflicts at PR time. Delete the feature branch after merging.

### Hotfix branches

- Branch from: `main`
- Merge into: `main`, then back-merge into `development`
- Naming: `hotfix/<version>/<description>` (e.g. `hotfix/1.2.1/fix-weight-nan`)

### Release branches

- Branch from: `development`
- Merge into: `development`, then `main` with a version tag
- Naming: `release/<version>` (e.g. `release/2.0.0`)

---

## Making a PR

1. Branch from `development` using the naming convention above
2. Each PR should cover one concern — feature, bug fix, or refactor, not a mix
3. Title format: `type(scope): description` (e.g. `refactor(validator): split forward.py`)
4. Update `docs/project-status.md` in the same PR when completing a migration step
5. Run the verification checklist below before marking ready for review

---

## Git strategy for file moves

Use `git mv` to preserve file history:

```bash
git mv base_miner natix/miner
git mv natix/synthetic_data_generation natix/validator/synthetic
git mv neurons/validator_proxy.py natix/validator/proxy/proxy.py
```

After moving, update imports. Run tests. Commit as one atomic change.

---

## Verifying a change

```bash
# 1. Imports still resolve
python -c "from natix.protocol import ImageSynapse"
python -c "from natix.miner.registry import DETECTOR_REGISTRY"
python -c "from natix.validator.proxy import ValidatorProxy"

# 2. Entry points respond
python neurons/miner.py --help
python neurons/validator.py --help

# 3. Tests
pytest tests/

# 4. Linting
flake8 natix/ neurons/
```

---

## Verifying dependency isolation

```bash
# Validator core — torch must not be present
python3.11 -m venv /tmp/test_validator
/tmp/test_validator/bin/pip install -e ".[validator]"
/tmp/test_validator/bin/python -c "import torch" && echo "FAIL: torch leaked" || echo "OK"
/tmp/test_validator/bin/python -c "from natix.protocol import ImageSynapse; print('OK')"
```

---

## Docker builds

```bash
docker build -f Dockerfile.miner -t natix-miner:test .
docker build -f Dockerfile.validator -t natix-validator:test .

# Smoke test
docker run --rm natix-miner:test python neurons/miner.py --help
docker run --rm natix-validator:test python neurons/validator.py --help
```
