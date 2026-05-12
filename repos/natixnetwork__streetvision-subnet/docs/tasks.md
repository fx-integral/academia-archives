# Migration Tasks

Ten steps to migrate from the current mixed structure to the clean architecture described in ARCHITECTURE.md. Each step is self-contained and should be done in order — later steps depend on earlier ones.

**Current status:** Steps 1–10 complete. Steps 11–13 pending.

---

## Step 1 — Create migration documentation ✅

Create ARCHITECTURE.md, TASKS.md, TECH_DECISIONS.md, PROJECT_STATUS.md, SPECIFICATIONS.md, WORKFLOW.md at project root.

**Why first:** Every subsequent step needs a shared reference point to avoid re-litigating decisions mid-task.

---

## Step 2 — Drop Poetry, switch to pip + venv, and isolate dependencies ✅

**Goal:** Miner and validator can be installed independently using plain pip and a standard venv. Drop Poetry entirely. DL libraries (torch, diffusers, etc.) become optional extras for the validator.

**Why drop Poetry:** The current `pyproject.toml` is already a hybrid — it uses the PEP 621 `[project]` header but puts dependencies in the Poetry-proprietary `[tool.poetry.dependencies]` section. The existing `start_validator.sh` already uses a plain `venv/`, not Poetry. Bittensor subnets standardly use pip. PEP 621 optional dependencies (`[project.optional-dependencies]`) give us the same extras mechanism without the extra toolchain.

**Changes:**

1. Migrate `pyproject.toml` to PEP 621 format:
   - Move deps from `[tool.poetry.dependencies]` to `[project.dependencies]` (core deps only)
   - Add `[project.optional-dependencies]` with four groups:
     - `miner` — torch==2.2.0, torchvision==0.17.0, torchaudio==2.2.0, timm, ultralytics, opencv-python, scikit-image, scikit-learn
     - `validator` — wandb, joblib, tensorboardx (core loop only, no DL, no heavy image processing)
     - `validator-image` — datasets, opencv-python, scikit-image, scikit-learn (HuggingFace cache + augmentation)
     - `validator-synthetic` — torch, torchvision, transformers, diffusers, accelerate, etc. (background synthetic generation process)
   - Add `dev` group for tooling (pytest, black, flake8, etc.)
   - Switch build backend from `poetry-core` to `hatchling`
   - Keep `requires-python = ">=3.10,<3.12"` (Python 3.11 required for bittensor 9.9.0)

2. Replace `requirements.txt` with role-specific files:
   - `requirements.miner.txt` — flat deps for miner Docker image
   - `requirements.validator.txt` — flat deps for validator (core + image pipeline, no DL)
   - `requirements.validator-full.txt` — flat deps for validator with synthetic generation

3. Update `Dockerfile.miner` and `Dockerfile.validator` to use pip + the appropriate requirements file

4. Update `start_miner.sh` and `start_validator.sh` to use `venv/bin/python` (validator already does; align miner)

5. Remove `poetry.lock`

**Install commands after this step:**
```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -e ".[miner]"                             # miner
pip install -e ".[validator]"                         # validator core (no DL)
pip install -e ".[validator,validator-synthetic]"     # full validator
```

**Verification:**
```bash
# Validator core: torch must not be importable
pip install -e ".[validator]"
python -c "import torch" && echo "FAIL" || echo "OK — torch not present"
# Protocol must be importable without torch
python -c "from natix.protocol import ImageSynapse; print('OK')"
```

**Files affected:**
- `pyproject.toml` (rewritten)
- `poetry.lock` (deleted)
- `requirements.txt` → split into `requirements.miner.txt`, `requirements.validator.txt`, `requirements.validator-full.txt`
- `Dockerfile.miner`
- `Dockerfile.validator`
- `start_miner.sh` (minor: align venv usage)

**Depends on:** Step 1

---

## Step 3 — Fix `protocol.py` dependency inversion ✅

**Goal:** `natix/protocol.py` must be importable with zero ML dependencies. Currently it imports `torch`, `torchvision`, and `natix/validator/config.TARGET_IMAGE_SIZE` at module level.

**Changes:**
- Create `natix/constants.py` with shared constants (start with `TARGET_IMAGE_SIZE`)
- Update `protocol.py` to import `TARGET_IMAGE_SIZE` from `natix/constants.py`
- Make the torch/torchvision imports inside `prepare_synapse()` lazy (only import when input is actually a tensor)
- Move the module-level `base_transforms = get_base_transforms(...)` call to inside `prepare_image_synapse()`
- Update any file that used `from natix.validator.config import TARGET_IMAGE_SIZE` for this constant specifically

**Files affected:**
- `natix/protocol.py`
- `natix/constants.py` (new)
- `natix/validator/config.py` (keep TARGET_IMAGE_SIZE there too for backward compat, import from constants)

**Depends on:** Step 1

---

## Step 4 — Move `base_miner/` → `natix/miner/` ✅

**Goal:** All miner-specific code lives under `natix/`, mirroring `natix/validator/`. The `base_miner/` directory at project root is eliminated.

**Changes:**
- Move `base_miner/` to `natix/miner/` (git mv to preserve history)
- Update all imports:
  - `neurons/miner.py`: `from base_miner.registry import DETECTOR_REGISTRY` → `from natix.miner.registry import DETECTOR_REGISTRY`
  - `neurons/miner.py`: `import base_miner.detectors` → `import natix.miner.detectors`
  - Any other file importing from `base_miner`
- Verify `neurons/miner.py` starts cleanly after the rename

**Files affected:**
- `base_miner/` → `natix/miner/` (entire directory, git mv)
- `neurons/miner.py`
- Any test files that import from `base_miner`

**Depends on:** Step 1

---

## Step 5 — Move `natix/synthetic_data_generation/` → `natix/validator/synthetic/` ✅

**Goal:** Validator-only code lives under `natix/validator/`. The top-level `natix/synthetic_data_generation/` is eliminated.

**Changes:**
- Move `natix/synthetic_data_generation/` to `natix/validator/synthetic/` (git mv)
- Update all imports referencing `natix.synthetic_data_generation`
- Verify `natix/validator/scripts/run_data_generator.py` still works

**Files affected:**
- `natix/synthetic_data_generation/` → `natix/validator/synthetic/` (git mv)
- `natix/validator/scripts/run_data_generator.py`
- Any imports in `natix/validator/` referencing the old path

**Depends on:** Step 1

---

## Step 6 — Move `neurons/validator_proxy.py` → `natix/validator/proxy/` ✅

**Goal:** Business logic out of the `neurons/` layer. `neurons/` should contain entry points only.

**Changes:**
- Create `natix/validator/proxy/` directory
- Move `neurons/validator_proxy.py` → `natix/validator/proxy/proxy.py` (git mv)
- Move `natix/validator/organic_task_distributor.py` → `natix/validator/proxy/task_distributor.py`
- Create `natix/validator/proxy/__init__.py` exposing `ValidatorProxy`
- Update `neurons/validator.py` import: `from neurons.validator_proxy import ValidatorProxy` → `from natix.validator.proxy import ValidatorProxy`
- The old `natix/validator/proxy.py` (currently a thin shell) gets replaced by the `proxy/` package

**Files affected:**
- `neurons/validator_proxy.py` → `natix/validator/proxy/proxy.py`
- `natix/validator/organic_task_distributor.py` → `natix/validator/proxy/task_distributor.py`
- `natix/validator/proxy.py` → deleted (replaced by `proxy/` package)
- `natix/validator/proxy/__init__.py` (new)
- `neurons/validator.py`

**Depends on:** Step 1

---

## Step 7 — Split `natix/validator/forward.py` ✅

**Goal:** `forward.py` becomes a thin orchestrator. Its four embedded concerns become separate modules.

**Changes:**
- Create `natix/validator/challenge/` with:
  - `selector.py` — `determine_challenge_type()` function
  - `augmentation.py` — thin wrapper over `apply_augmentation_by_level` with challenge-specific logic
  - `api_task.py` — `fetch_api_challenge()` and S3 image download
- Keep `forward.py` as an orchestrator that imports from `challenge/` and calls `get_rewards()`
- The `statistics_assign_task` / `statistics_report_task` functions stay in `forward.py` temporarily (consolidated in Step 8)

**Files affected:**
- `natix/validator/forward.py` (trimmed to orchestrator)
- `natix/validator/challenge/` (new directory, 3 files + `__init__.py`)

**Depends on:** Steps 1, 6

---

## Step 8 — Consolidate statistics reporting into `api_client.py` ✅

**Goal:** Eliminate the three copies of `statistics_assign_task` / `statistics_report_task`. One implementation, one place.

**Current duplication:**
- `natix/validator/forward.py` — batch version (`List[float]`)
- `natix/validator/proxy/task_distributor.py` — single version (`float`)
- `natix/validator/proxy/proxy.py` — calls forward.py version

**Changes:**
- Move both `statistics_assign_task` and `statistics_report_task` into `natix/validator/api_client.py`
- Unify the two signatures (single + batch both supported, or separate functions clearly named)
- Remove duplicates from `forward.py` and `proxy/`
- Update all call sites to import from `api_client`

**Files affected:**
- `natix/validator/api_client.py`
- `natix/validator/forward.py`
- `natix/validator/proxy/proxy.py`
- `natix/validator/proxy/task_distributor.py`

**Depends on:** Steps 6, 7

---

## Step 9 — Thin entry points in `neurons/` ✅

**Goal:** `neurons/miner.py` and `neurons/validator.py` contain no business logic. They only parse arguments, instantiate the main class, and run the loop.

**Changes:**
- Audit `neurons/validator.py`: `init_wandb()` and `store_vali_info()` are business logic — move them into `natix/validator/` (e.g., `natix/validator/monitoring.py`)
- `neurons/miner.py` is already close to thin — review and clean up if needed
- Verify `neurons/` only imports from `natix/` (no cross-imports between neuron files)

**Files affected:**
- `neurons/validator.py`
- `natix/validator/monitoring.py` (new, receives wandb init logic)

**Depends on:** Steps 4, 6, 7, 8

---

## Step 10 — Validation, cleanup, and Dockerfile verification ✅

**Goal:** Confirm the full migration is correct and all install paths work.

**Checklist:**
- [ ] `pip install -e ".[miner]"` in a fresh venv — no torch leaks to validator install
- [ ] `pip install -e ".[validator]"` in a fresh venv — no torch installed, `import torch` fails
- [ ] `pip install -e ".[validator,validator-image,validator-synthetic]"` — full validator installs cleanly
- [ ] `python -c "from natix.protocol import ImageSynapse"` works without torch installed
- [ ] `python neurons/miner.py --help` works
- [ ] `python neurons/validator.py --help` works
- [ ] All tests pass: `pytest tests/`
- [ ] `Dockerfile.miner` builds and runs
- [ ] `Dockerfile.validator` builds and runs
- [ ] Update `ARCHITECTURE.md` to mark migration complete
- [ ] Update `PROJECT_STATUS.md` with final state

**Depends on:** All previous steps

---

## Step 11 — Create `natix/validator/challenge/augmentation.py` ✅

**Goal:** Complete the challenge/ split from Step 7. The augmentation wrapper was never created — `forward.py` still calls `apply_augmentation_by_level` directly from `natix.utils.image_transforms`.

**Why it matters:** Per SPECIFICATIONS.md, `challenge/` owns everything related to constructing a single challenge, including augmentation. Keeping the augmentation call in `forward.py` leaves a leaky abstraction that mixes orchestration with challenge-building logic.

**Changes:**
- Create `natix/validator/challenge/augmentation.py` with a single function:
  - `augment_challenge(image, size, mask_center)` → `(image, level, params)`  
  - Thin wrapper over `natix.utils.image_transforms.apply_augmentation_by_level`
- Update `natix/validator/forward.py` to import and call `augment_challenge` instead of calling `apply_augmentation_by_level` directly
- Update `natix/validator/challenge/__init__.py` to export `augment_challenge`

**Files affected:**
- `natix/validator/challenge/augmentation.py` (new)
- `natix/validator/challenge/__init__.py`
- `natix/validator/forward.py`

**Depends on:** Step 7

---

## Step 12 — Move inference code out of `neurons/miner.py` ✅

**Goal:** `neurons/miner.py` becomes a true entry point. Currently it contains `forward_image()` (inference) and `load_image_detector()` (model loading) — both are business logic that violates the SPECIFICATIONS.md rule: "Must NOT contain: Business logic, model definitions, inference code."

**Changes:**
- Create `natix/miner/neuron.py` containing a `Miner` class (subclass of `BaseMinerNeuron`) with:
  - `load_image_detector()` — model loading
  - `forward_image()` — inference handler
  - `blacklist_image()` / `priority_image()` — axon hooks
  - `save_state()`
- Slim `neurons/miner.py` to ~30 lines: import `Miner` from `natix.miner.neuron`, parse args, run loop
- Update `tests/test_miner.py` import accordingly

**Files affected:**
- `natix/miner/neuron.py` (new)
- `neurons/miner.py` (trimmed to entry point)
- `tests/test_miner.py`

**Depends on:** Step 4

---

## Step 13 — Create `natix/validator/scoring/` and relocate reward + performance tracker ✅

**Goal:** Align with the target architecture in ARCHITECTURE.md. `reward.py` and `MinerPerformanceTracker` belong together under `natix/validator/scoring/` — they are both validator scoring concerns, not base-layer concerns.

**Current locations (wrong):**
- `natix/validator/reward.py` — should be `natix/validator/scoring/reward.py`
- `natix/base/miner_performance_tracker.py` — should be `natix/validator/scoring/performance_tracker.py`

**Changes:**
- Create `natix/validator/scoring/` directory
- Move `natix/validator/reward.py` → `natix/validator/scoring/reward.py` (git mv)
- Move `natix/base/miner_performance_tracker.py` → `natix/validator/scoring/performance_tracker.py` (git mv)
- Create `natix/validator/scoring/__init__.py` exporting `get_rewards` and `MinerPerformanceTracker`
- Update `natix/base/validator.py` import: `from natix.base.miner_performance_tracker` → `from natix.validator.scoring.performance_tracker` (this is explicitly allowed by SPECIFICATIONS.md)
- Update `natix/validator/forward.py` import: `from natix.validator.reward` → `from natix.validator.scoring`
- Update any other call sites

**Files affected:**
- `natix/validator/reward.py` → `natix/validator/scoring/reward.py`
- `natix/base/miner_performance_tracker.py` → `natix/validator/scoring/performance_tracker.py`
- `natix/validator/scoring/__init__.py` (new)
- `natix/base/validator.py`
- `natix/validator/forward.py`
- Any tests importing from the old paths

**Depends on:** Step 8

---

## Step 14 — Consolidate root-level operational files into `scripts/` ✅

**Goal:** Reduce root clutter by moving operational shell scripts and PM2 configs into a `scripts/` directory. The root currently has 11 operational files that are not Python packaging conventions.

**Files to move:**
- `start_miner.sh` → `scripts/start_miner.sh`
- `start_validator.sh` → `scripts/start_validator.sh`
- `start_cache_updater.sh` → `scripts/start_cache_updater.sh`
- `start_synthetic_generator.sh` → `scripts/start_synthetic_generator.sh`
- `setup_env.sh` → `scripts/setup_env.sh`
- `register.sh` → `scripts/register.sh`
- `autoupdate_miner_steps.sh` → `scripts/autoupdate_miner_steps.sh`
- `autoupdate_validator_steps.sh` → `scripts/autoupdate_validator_steps.sh`
- `run_neuron.py` → `scripts/run_neuron.py`
- `ecosystem.miner.config.js` → `scripts/ecosystem.miner.config.js`
- `ecosystem.validator.config.js` → `scripts/ecosystem.validator.config.js`

**Files that stay at root** (conventions or operator convenience):
- `pyproject.toml`, `README.md`, `LICENSE`, `.gitignore`, `.pre-commit-config.yaml` — Python/Git standards
- `min_compute.yml` — Bittensor subnet convention (queried at root)
- `Dockerfile.miner`, `Dockerfile.validator` — Docker Hub auto-build convention
- `requirements.*.txt` — referenced directly by Dockerfiles
- `miner.env`, `validator.env` — operators need to find and edit these easily

**Changes:**
- `git mv` each file into `scripts/`
- Update any cross-references between scripts (e.g., `start_validator.sh` calling `start_cache_updater.sh`)
- Update `WORKFLOW.md` to reference `scripts/start_validator.sh` etc.
- Update `README.md` if it references any of these paths
- Update PM2 ecosystem configs if they reference script paths

**Depends on:** Step 1 (independent of all other steps)

---

## Step ordering summary

```
1 (docs)
├── 2 (deps)        — independent of 3-9, can do in parallel
├── 3 (protocol)    — independent of 4-9, can do in parallel
├── 4 (base_miner)  — independent of 5-9
│   └── 12 (thin miner neuron)
├── 5 (synthetic)   — independent of 4, 6-9
├── 6 (proxy)
│   └── 7 (forward split)
│       ├── 11 (augmentation.py)
│       └── 8 (stats consolidation)
│           └── 9 (thin neurons)
│               └── 10 (validation)
├── 13 (scoring/)   — depends on 8
└── 14 (scripts/)   — independent, depends only on Step 1
```

Steps 2, 3, 4, 5 can be done in any order after Step 1. Steps 11, 12, 13, 14 are independent of each other and can be done in any order.
