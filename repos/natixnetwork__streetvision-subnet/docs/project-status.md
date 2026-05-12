# Project Status

Last updated: 2026-05-03. Migration complete — all 14 steps done.

---

## Migration progress

| Step | Description | Status |
|------|-------------|--------|
| 1 | Create migration documentation | ✅ Done |
| 2 | Drop Poetry, pip + venv, dependency isolation | ✅ Done |
| 3 | Fix `protocol.py` dependency inversion | ✅ Done |
| 4 | Move `base_miner/` → `natix/miner/` | ✅ Done |
| 5 | Move `natix/synthetic_data_generation/` → `natix/validator/synthetic/` | ✅ Done |
| 6 | Move `neurons/validator_proxy.py` → `natix/validator/proxy/` | ✅ Done |
| 7 | Split `natix/validator/forward.py` | ✅ Done |
| 8 | Consolidate statistics reporting into `api_client.py` | ✅ Done |
| 9 | Thin entry points in `neurons/` | ✅ Done |
| 10 | Validation, cleanup, Dockerfile verification | ✅ Done |
| 11 | Create `natix/validator/challenge/augmentation.py` | ✅ Done |
| 12 | Move inference code out of `neurons/miner.py` | ✅ Done |
| 13 | Create `natix/validator/scoring/` | ✅ Done |
| 14 | Consolidate root-level operational files into `scripts/` | ✅ Done |

---

## Current branch

`re-architecture` — ready to merge to `main`.

---

## Known remaining issues

### Dockerfiles not smoke-tested post-migration
`Dockerfile.miner` and `Dockerfile.validator` were updated in Step 2 but not built in CI. Verify with:
```bash
docker build -f Dockerfile.miner -t natix-miner:test .
docker build -f Dockerfile.validator -t natix-validator:test .
```

### `test_forward.py` requires live cache state
`tests/test_forward.py` uses `MockValidator` which now provides stub caches. The test passes structurally but exercises the challenge loop shallowly. Deeper integration tests should be added for `natix/validator/challenge/` modules.

---

## Dependency footprint

Four independently installable extras groups in `pyproject.toml`:

| Install command | Gets |
|----------------|------|
| `pip install -e ".[miner]"` | torch, timm, ultralytics, opencv, scikit-image |
| `pip install -e ".[validator]"` | wandb, joblib — no DL, no heavy image libs |
| `pip install -e ".[validator,validator-image]"` | + datasets, opencv, scikit-image |
| `pip install -e ".[validator,validator-image,validator-synthetic]"` | + torch, diffusers, transformers |

Requirements files for Docker:
- `requirements.miner.txt`
- `requirements.validator.txt` (core + image pipeline)
- `requirements.validator-full.txt` (core + image + synthetic)

---

## Final module layout

```
natix/
  constants.py              # shared: TARGET_IMAGE_SIZE
  protocol.py               # shared synapse, torch-free at import time
  base/                     # chain/axon primitives, no ML deps
  utils/                    # shared utilities, no validator/miner deps
  miner/                    # all miner ML code (detectors, datasets, registry, Miner class)
  validator/
    api_client.py           # all proxy API calls + statistics reporting
    challenge/              # challenge selection, S3 fetch, augmentation (augment_challenge)
    cache/                  # HuggingFace parquet download + image cache
    proxy/                  # organic task polling + distribution
    scoring/                # reward computation (reward.py) + performance tracker (performance_tracker.py)
    synthetic/              # diffusion-based image generation (optional)
    monitoring.py           # wandb lifecycle
    forward.py              # orchestrator loop
neurons/
  miner.py                  # entry point: ~25 lines (Miner class lives in natix/miner/neuron.py)
  validator.py              # entry point: ~64 lines
```
