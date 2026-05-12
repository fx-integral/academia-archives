# Architecture

This document describes the current state of the codebase and the target architecture after the planned migration. It is written for an AI assistant starting a new conversation with no prior context.

---

## What this project is

A **Bittensor subnet** called NATIX. It runs decentralized image classification for detecting roadwork/construction in images.

Two types of participants:
- **Validators** — send image challenges to miners, score responses, set weights on-chain
- **Miners** — receive images via axon, run a classification model, return a probability score

They communicate using the Bittensor network (chain registration, metagraph) and direct axon/dendrite calls (the Bittensor P2P layer).

---

## Current directory layout

```
subnet/
  neurons/
    miner.py              # entry point + some business logic
    validator.py          # entry point + wandb init + validator state
    validator_proxy.py    # organic task handler — NOT an entry point, wrongly placed here

  natix/
    __init__.py
    protocol.py           # shared synapse — BUT imports torch and natix/validator/config (broken dep)

    base/
      neuron.py           # base chain/axon setup (shared)
      miner.py            # BaseMinerNeuron (axon, blacklist, priority)
      validator.py        # BaseValidatorNeuron (dendrite, scoring, weights)
      utils/
        weight_utils.py

    utils/                # shared utilities
      config.py
      image_transforms.py
      logging.py
      misc.py
      mock.py
      uids.py
      wandb_utils.py

    validator/            # validator-specific logic
      forward.py          # DUMPING GROUND: S3 fetch + stats reporting + challenge select + forward loop
      reward.py
      miner_performance_tracker.py
      organic_task_distributor.py
      api_client.py       # only contains build_auth_headers() — understaffed
      proxy.py            # thin shell, barely used
      config.py
      model_utils.py
      verify_models.py
      cache/
        base_cache.py
        image_cache.py
        download.py
        extract.py
        util.py
      scripts/
        run_cache_updater.py
        run_data_generator.py
        util.py

    synthetic_data_generation/   # validator-only but outside natix/validator/
      synthetic_data_generator.py
      prompt_generator.py
      prompt_utils.py
      image_utils.py

  base_miner/             # miner-only but outside natix/ entirely
    config.py
    registry.py
    detectors/
      feature_detector.py
      roadwork_detector.py
      vit_detector.py
      configs/constants.py
    datasets/
      base_dataset.py
      image_dataset.py
      real_fake_dataset.py
      download_data.py
      util.py
    gating_mechanisms/
      gating_mechanism.py
      gate.py
      roadwork_gate.py
      utils/face_utils.py
```

---

## Current structural problems

### 1. `base_miner/` lives outside `natix/`
All miner model code (detectors, datasets, gating) is at root level while the validator equivalent is correctly nested under `natix/validator/`. This is the most visible naming inconsistency. It belongs at `natix/miner/`.

### 2. `neurons/validator_proxy.py` is business logic in the entry point layer
`validator_proxy.py` contains 155 lines of real logic: API polling, S3 download, miner querying, scoring. It imports from `natix/validator/` extensively. It is not an entry point — it should live in `natix/validator/proxy/`.

### 3. `natix/validator/forward.py` is a dumping ground
It contains four distinct concerns in one file:
- `fetch_api_challenge()` — S3 image download
- `statistics_assign_task()` / `statistics_report_task()` — API reporting (duplicated in `organic_task_distributor.py` and `validator_proxy.py`)
- `determine_challenge_type()` — challenge selection logic
- `forward()` — the orchestration loop

### 4. `protocol.py` has an inverted dependency
`natix/protocol.py` (shared contract) imports from `natix/validator/config.py` to get `TARGET_IMAGE_SIZE`. The shared layer must not depend on role-specific code. Additionally it imports `torch` and `torchvision` at module level, meaning `import natix.protocol` eagerly loads PyTorch — this forces both miner and validator to always have DL deps even when not needed.

### 5. Statistics reporting is copy-pasted in three places
`statistics_assign_task` and `statistics_report_task` exist in:
- `natix/validator/forward.py` (batch version: takes `List[float]`)
- `natix/validator/organic_task_distributor.py` (single version: takes `float`)
- `neurons/validator_proxy.py` (calls the forward.py version directly)
The two versions have subtle signature differences.

### 6. All dependencies are bundled into one `pyproject.toml`
Every ML library (torch, diffusers, ultralytics, transformers) is required for both miner and validator installs. A validator can run without synthetic generation; a validator-core-only install should weigh ~500MB, not ~10GB.

### 7. `natix/synthetic_data_generation/` is in the wrong namespace
This is validator-only code (diffusion models, prompt generation). It should be under `natix/validator/synthetic/`.

---

## Target architecture

```
subnet/
  neurons/
    miner.py          # thin: parse args, load detector, attach axon handlers, run loop
    validator.py      # thin: instantiate Validator, run loop

  natix/
    protocol.py       # ImageSynapse, prepare_synapse() — NO validator imports, lazy torch

    base/             # chain/axon primitives (shared, no ML deps)
      neuron.py
      miner.py
      validator.py
      utils/weight_utils.py

    constants.py      # shared constants: TARGET_IMAGE_SIZE, etc.

    utils/            # shared utilities (no ML deps except image_transforms which needs Pillow)
      config.py
      image_transforms.py
      logging.py
      misc.py
      mock.py
      uids.py
      wandb_utils.py

    miner/            # ← was base_miner/
      config.py
      registry.py
      detectors/
        feature_detector.py
        roadwork_detector.py
        vit_detector.py
        configs/constants.py
      datasets/
      gating_mechanisms/

    validator/
      forward.py      # thin orchestrator only: calls challenge/, scoring/, api_client
      config.py
      model_utils.py
      verify_models.py
      miner_performance_tracker.py

      challenge/      # ← split from forward.py
        selector.py           # determine_challenge_type()
        augmentation.py       # apply_augmentation_by_level wrapper
        api_task.py           # fetch_api_challenge() + S3 download

      scoring/        # ← from reward.py + performance_tracker
        reward.py
        performance_tracker.py

      cache/          # already well-structured, no changes
        base_cache.py
        image_cache.py
        download.py
        extract.py
        util.py

      synthetic/      # ← was natix/synthetic_data_generation/
        synthetic_data_generator.py
        prompt_generator.py
        prompt_utils.py
        image_utils.py

      proxy/          # ← merge neurons/validator_proxy.py + organic_task_distributor.py
        proxy.py              # polling loop, main entry
        task_distributor.py   # miner selection, staggered send

      api_client.py   # auth headers + ALL statistics reporting (deduplicated)

      scripts/        # background processes (unchanged)
        run_cache_updater.py
        run_data_generator.py
        util.py
```

---

## Dependency isolation (post-migration)

Four installable extras groups in `pyproject.toml` (`[project.optional-dependencies]`).
No Poetry — plain pip + venv.

```bash
python3.11 -m venv venv && source venv/bin/activate

pip install -e ".[miner]"                                          # miner only
pip install -e ".[validator]"                                      # validator core (no DL, no image processing)
pip install -e ".[validator,validator-image]"                      # + HuggingFace cache + augmentation
pip install -e ".[validator,validator-image,validator-synthetic]"  # full validator
```

Key principle: `natix.protocol`, `natix.base.*`, and `natix.utils.*` must be importable with **zero ML dependencies** (only `bittensor`, `httpx`, `Pillow`, `numpy`).

---

## How miner and validator communicate

1. Both register a hotkey on the Bittensor chain.
2. Validator reads the metagraph to find miner axon endpoints.
3. Validator sends an `ImageSynapse` to a miner axon via `bt.dendrite`.
4. Miner's axon receives the synapse, calls `forward_image()`, fills in `synapse.prediction`, returns it.
5. Validator scores the prediction via `get_rewards()` in `natix/validator/scoring/reward.py`.
6. Validator calls `self.update_scores()` → `set_weights()` on-chain periodically.

The `ImageSynapse` in `natix/protocol.py` is the shared contract: it carries a base64-encoded JPEG and returns a float prediction (0.0 = real, 1.0 = AI-generated).
