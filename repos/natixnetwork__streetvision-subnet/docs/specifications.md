# Module Specifications

Defines what each module owns, what it may import, and the interfaces between modules. This is the contract for the target architecture (post-migration). Use it to decide where new code belongs.

---

## Layering rules

Dependencies must flow in one direction only:

```
neurons/          →  natix/validator/  →  natix/base/  →  natix/protocol.py
neurons/          →  natix/miner/      →  natix/base/  →  natix/constants.py
natix/validator/  →  natix/utils/
natix/miner/      →  natix/utils/
natix/base/       →  natix/utils/
```

**Forbidden:**
- `natix/protocol.py` importing from `natix/validator/` or `natix/miner/`
- `natix/base/` importing from `natix/validator/` or `natix/miner/`
- `natix/utils/` importing from any role-specific module
- `neurons/` files importing from each other

---

## `natix/protocol.py`

**Owns:** The shared wire format between miner and validator.

**Exports:**
- `ImageSynapse` — Pydantic/Bittensor synapse: carries base64 JPEG image, returns float prediction
- `prepare_synapse(input_data, modality)` — converts PIL Image or torch.Tensor to `ImageSynapse`
- `prepare_image_synapse(image)` — converts a single PIL Image to `ImageSynapse`

**May import:** `natix.constants`, `natix.utils.image_transforms`. Nothing else from `natix/`.

**Must NOT import:** `natix.validator.*`, `natix.miner.*`, `torch` at module level.

**Invariant:** `from natix.protocol import ImageSynapse` must work with zero ML packages installed.

---

## `natix/constants.py`

**Owns:** Values fixed by the protocol that must be identical for miner and validator.

**Exports:** `TARGET_IMAGE_SIZE` (int), any future protocol-level constants.

**May import:** Nothing from `natix/`.

---

## `natix/base/neuron.py`

**Owns:** Base class for all neurons. Chain registration, metagraph, subtensor, wallet, config parsing.

**May import:** `bittensor`, `natix.utils.config`.

**Must NOT import:** `torch`, `natix.validator.*`, `natix.miner.*`.

---

## `natix/base/miner.py`

**Owns:** `BaseMinerNeuron` — axon lifecycle, blacklist, priority, run loop.

**May import:** `bittensor`, `natix.base.neuron`, `natix.utils.*`.

**Must NOT import:** `natix.validator.*`, `natix.miner.*` (model loading belongs in `neurons/miner.py`).

---

## `natix/base/validator.py`

**Owns:** `BaseValidatorNeuron` — dendrite, scoring (EMA), weight setting, state persistence, miner history.

**May import:** `bittensor`, `natix.base.neuron`, `natix.utils.*`, `natix.validator.miner_performance_tracker`.

**Must NOT import:** `natix.miner.*`, `torch` (scoring uses only numpy).

---

## `natix/miner/` (target, formerly `base_miner/`)

**Owns:** All miner ML code — detector implementations, training datasets, gating mechanisms, model registry.

**Exports:**
- `natix.miner.registry.DETECTOR_REGISTRY` — maps string names to detector classes
- `natix.miner.detectors.*` — `RoadworkDetector`, `ViTDetector`, `FeatureDetector`
- `natix.miner.datasets.*` — dataset loaders for training
- `natix.miner.gating_mechanisms.*` — task filtering

**May import:** `torch`, `torchvision`, `timm`, `ultralytics`, `opencv-python`, `Pillow`.

**Must NOT import:** `natix.validator.*`.

**DL dependency group:** `[miner]` extras.

---

## `natix/validator/challenge/`

**Owns:** Everything related to constructing a single challenge — picking the source, fetching the image, applying augmentation.

**Exports:**
- `selector.determine_challenge_type(media_cache, synthetic_cache)` → `(label, modality, task, cache, source)`
- `augmentation.augment_challenge(image, size, mask_center)` → `(image, level, params)`
- `api_task.fetch_api_challenge(validator, label)` → `dict | None`

**May import:** `httpx`, `Pillow`, `natix.utils.image_transforms`, `natix.validator.api_client`, `natix.validator.config`.

**Must NOT import:** `torch` at module level (augmentation uses opencv/PIL, not torch).

---

## `natix/validator/scoring/`

**Owns:** Reward computation and per-miner performance tracking.

**Exports:**
- `reward.get_rewards(label, responses, uids, axons, performance_trackers)` → `(np.ndarray, List[Dict])`
- `performance_tracker.MinerPerformanceTracker`

**May import:** `numpy`, `bittensor`, `natix.validator.config`.

**Must NOT import:** `torch`.

---

## `natix/validator/cache/`

**Owns:** Parquet-based image cache management. Downloads datasets from HuggingFace, extracts images, serves them to the forward loop.

**Exports:**
- `ImageCache(cache_dir, ...)` — manages a local image cache
- `ImageCache.sample(label)` → `dict | None`
- `ImageCache.update()` — downloads new parquets, refreshes extracted images

**May import:** `Pillow`, `datasets` (HuggingFace), `natix.validator.config`.

**Must NOT import:** `torch`. Dataset download uses the HuggingFace `datasets` library, not ML models.

---

## `natix/validator/synthetic/` (target, formerly `natix/synthetic_data_generation/`)

**Owns:** Synthetic image generation using diffusion models. Runs as a background process, writes images to disk for `ImageCache` to pick up.

**Exports:**
- `SyntheticDataGenerator` — orchestrates LLM prompt generation + diffusion image generation
- `PromptGenerator` — generates text prompts for synthetic scenes

**May import:** `torch`, `torchvision`, `diffusers`, `transformers`, `accelerate`, `sentencepiece`.

**DL dependency group:** `[validator-synthetic]` extras. This module is **optional** — the validator runs without it (using only real images from the cache and API tasks).

---

## `natix/validator/proxy/`

**Owns:** Organic task handling — polling the API for consensus tasks, distributing to miners, collecting predictions.

**Exports:**
- `ValidatorProxy(validator)` — starts background polling thread on init
- `OrganicTaskDistributor(validator, ...)` — handles miner selection, deduplication, staggered sends

**May import:** `bittensor`, `httpx`, `natix.protocol`, `natix.validator.api_client`, `natix.validator.scoring`, `natix.utils.*`.

**Must NOT import:** `torch`.

**Note:** This module replaces both the old `neurons/validator_proxy.py` and `natix/validator/organic_task_distributor.py`.

---

## `natix/validator/api_client.py`

**Owns:** All communication with the external proxy API (not the Bittensor chain). Auth headers, task requests, statistics reporting.

**Exports:**
- `build_auth_headers(wallet)` → `dict`
- `statistics_assign_task(validator, miner_uid_list, type, label, payload_ref)` → `dict | None`
- `statistics_report_task_batch(validator, miner_uid_list, predictions, task_id)` → `dict | None`
- `statistics_report_task_single(validator, miner_uid, prediction, task_id)` → `dict | None`

**May import:** `httpx`, `bittensor`.

**Must NOT import:** `torch`, `natix.validator.forward`.

---

## `natix/validator/forward.py`

**Owns (post-migration):** The orchestration loop for benchmark challenges. Calls into `challenge/`, `scoring/`, `api_client`, and updates validator state. No embedded logic of its own.

**Size target:** Under 80 lines after Step 7.

---

## `neurons/miner.py`

**Owns:** Entry point only. Parses CLI args, loads the detector from `natix.miner.registry`, attaches axon handlers, runs the loop.

**Must NOT contain:** Business logic, model definitions, inference code.

**Target size:** ~60 lines (currently ~125, some is business logic that belongs in `natix/miner/`).

---

## `neurons/validator.py`

**Owns:** Entry point only. Parses CLI args, instantiates `Validator`, runs the loop.

**Must NOT contain:** wandb initialization logic, state serialization, organic proxy threading. These belong in `natix/validator/`.

**Target size:** ~30 lines (currently ~230, most is wandb init and state management that belongs in `natix/validator/`).
