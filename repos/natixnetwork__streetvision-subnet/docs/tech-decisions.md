# Technical Decisions

Records of significant architectural decisions — what was chosen, why, and what alternatives were rejected. Prevents re-arguing settled questions in future sessions.

---

## TD-001: Monorepo over split repos

**Decision:** Keep miner and validator code in a single repository.

**Rationale:** The `natix/protocol.py` synapse definition must be identical for both miner and validator. A protocol change (e.g., adding a field to `ImageSynapse`) must be atomic across both sides. With a split repo this requires coordinated PRs across 2+ repos — in practice this is the #1 source of bugs in active Bittensor subnets. One repo means one PR, one review, one deploy.

**Alternative considered:** Three-repo model (`natix-core`, `natix-miner`, `natix-validator`). Rejected because the coordination overhead outweighs the isolation benefit at this team size.

**Constraint:** This decision only holds while the protocol changes frequently. If the protocol stabilizes, revisit.

---

## TD-002: pip + venv over Poetry; PEP 621 optional dependencies for isolation

**Decision:** Drop Poetry. Use plain pip + venv with a PEP 621 `pyproject.toml` (`[project.optional-dependencies]`). Build backend is `hatchling`.

**Rationale:** The existing `pyproject.toml` was already a hybrid — PEP 621 `[project]` header but Poetry-proprietary `[tool.poetry.dependencies]`. `start_validator.sh` already used a plain `venv/`, not Poetry. The Bittensor subnet community standardly uses pip. PEP 621 optional dependencies give the same extras mechanism (`pip install ".[miner]"`) without requiring Poetry to be installed. One fewer tool in the setup chain, simpler CI, simpler Dockerfiles.

**Alternative considered:** Keep Poetry, just restructure the `[tool.poetry.extras]` section. Rejected because Poetry is an extra toolchain dependency that adds friction for contributors and is inconsistent with how the project already operated in practice.

**Install pattern:**
- `pip install -e ".[miner]"` — miner only
- `pip install -e ".[validator]"` — validator core (no DL, no image processing)
- `pip install -e ".[validator,validator-image]"` — validator + cache/augmentation
- `pip install -e ".[validator,validator-image,validator-synthetic]"` — full validator

**Alternative considered:** `requirements.miner.txt` / `requirements.validator.txt` flat files used by Docker only. Kept as secondary artifacts for Docker layer caching, not the source of truth.

---

## TD-003: Lazy torch imports in `protocol.py`

**Decision:** The torch/torchvision imports in `natix/protocol.py` must be inside the function body, not at module level.

**Rationale:** `protocol.py` is the shared contract imported by both miner and validator. If torch is imported at module level, installing the validator without `[validator-synthetic]` extras breaks on `import natix.protocol`. The tensor-handling path in `prepare_synapse()` is only exercised when the caller has torch tensors (i.e., the synthetic generation path). Making the import lazy means the protocol is importable in a torch-free environment.

**Implementation:** Move `import torch` and `from torchvision import transforms` inside the `if isinstance(input_data, torch.Tensor)` branch. Use `importlib.import_module` or a try/except if preferred.

---

## TD-004: `base_transforms` must not be computed at module level in `protocol.py`

**Decision:** The line `base_transforms = get_base_transforms(TARGET_IMAGE_SIZE)` that runs at import time must be moved inside the function that uses it.

**Rationale:** Module-level side effects at import time mean that importing `natix.protocol` triggers `get_base_transforms()` which eventually calls into torchvision. This breaks the lazy-import approach from TD-003. The performance cost of computing transforms on each call is negligible.

---

## TD-005: `natix/constants.py` as the shared constants file

**Decision:** Constants needed by both the shared layer (`protocol.py`, `base/`) and role-specific code go into `natix/constants.py`.

**Rationale:** `TARGET_IMAGE_SIZE` is currently defined in `natix/validator/config.py` and imported by `natix/protocol.py` — a layering violation. Moving it to `natix/constants.py` fixes the dependency direction. `natix/validator/config.py` can re-export it from `constants.py` for backward compatibility.

**What belongs in `constants.py`:** Only values that are fixed by the protocol and shared across miner/validator. Runtime-configurable values (paths, thresholds, intervals) stay in role-specific config files.

---

## TD-006: `neurons/` contains entry points only

**Decision:** The `neurons/` directory must contain only entry points — files that parse arguments, instantiate the main class, and run the event loop. No business logic.

**Rationale:** `neurons/validator_proxy.py` currently contains 155 lines of polling, S3 download, miner querying, and scoring logic while sitting next to the entry point. This makes it impossible to test without running the full validator. Business logic belongs in `natix/validator/` where it can be imported, unit-tested, and reasoned about in isolation.

**Corollary:** If a file in `neurons/` imports from another file in `neurons/`, that's a sign one of them contains business logic that should move to `natix/`.

---

## TD-007: Statistics reporting belongs in `api_client.py`

**Decision:** All calls to the statistics API (`/tasks/statistics/assign`, `/tasks/statistics/report`) are routed through `natix/validator/api_client.py`. No other file re-implements these functions.

**Rationale:** The same functions are currently copy-pasted in three places with subtle signature differences (batch vs. single prediction). A change to the API contract (e.g., adding a field) requires updating all three copies. Centralizing in `api_client.py` makes the API surface explicit and reduces the risk of divergence.

---

## TD-008: `natix/validator/forward.py` becomes an orchestrator, not a module

**Decision:** After Step 7, `forward.py` calls into `challenge/`, `scoring/`, and `api_client/` but contains no substantive logic of its own.

**Rationale:** The current `forward.py` mixes four concerns that need to be independently testable: challenge selection, augmentation, S3 fetch, and the scoring loop. Separating them makes each unit testable without needing the full validator context. The orchestrator pattern (thin `forward()` that calls into single-purpose modules) is more readable and maintainable.

---

## TD-009: `natix/validator/synthetic/` not `natix/synthetic_data_generation/`

**Decision:** Synthetic image generation code lives under `natix/validator/synthetic/`, not at the top-level `natix/` namespace.

**Rationale:** Synthetic generation is a validator-only concern. Placing it at the `natix/` level implies it's shared, which would require the miner to have diffusers/transformers available. Moving it under `natix/validator/` makes the dependency flow explicit and enables the `[validator-synthetic]` extras group to cover exactly this code.
