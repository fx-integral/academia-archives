"""Shared test fixtures for the validator test suite."""

from __future__ import annotations

import os

# Ensure tests don't fail due to .env loading BT_NETWORK=finney.
# Tests should work regardless of the local .env file.
os.environ["BT_NETWORK"] = "test"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")

# R25-07: Enable SPDZ simulation mode so tests can reconstruct alpha.
# Production code will refuse to reconstruct alpha without this flag.
os.environ["DJINN_SPDZ_SIMULATION"] = "1"

# v1723 made buyer_signature mandatory on /v1/signal/{id}/purchase.
# Tests that exercise routing/existence logic don't construct signed
# payloads; opt them out so the signature gate doesn't shadow the
# behavior they're actually checking. Tests that exercise the gate
# itself can override via monkeypatch.
os.environ["DJINN_ALLOW_UNSIGNED_PURCHASE"] = "1"
