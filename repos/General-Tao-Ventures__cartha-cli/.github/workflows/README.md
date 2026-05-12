# GitHub Actions Workflows

This directory contains GitHub Actions workflows for the Cartha CLI.

## Workflows

### `ci.yml`

Runs on every push and pull request to `main` and `demo-verifier` branches.

**Jobs:**
- **test**: Runs the test suite using `pytest`
- **lint**: Runs `ruff check` and `ruff format --check` to ensure code quality
- **type-check**: Runs `mypy` for type checking (non-blocking)

**Status Checks:**
- For pull requests, the test job sets a commit status that appears in the PR checks

## Local Development

You can run the same checks locally:

```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check cartha_cli tests
uv run ruff format --check cartha_cli tests

# Run type checking
uv run mypy cartha_cli
```

Or use the Makefile:

```bash
make test      # Runs lint, typecheck, and tests
make lint      # Runs ruff check
make format    # Formats code with ruff
make typecheck # Runs mypy
```

