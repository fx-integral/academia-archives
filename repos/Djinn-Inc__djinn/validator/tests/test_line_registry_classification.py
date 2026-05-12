"""v1763: revert-error classification in LineOutcomeSubmitter.submit.

Pre-v1763, classification matched only the human-readable contract error
name ("AlreadyFinalized", "InvalidOutcome", ...). Production web3.py
surfaces the 4-byte selector instead (e.g. "0x475a2535"), so every revert
fell through to "transient" and was retried forever — operator diag
showed thousands of wasted submit attempts per validator.

These tests pin both forms (name AND selector) for every classified
error, plus AlreadyAttested → terminal-success (own-EOA already on chain;
no point retrying).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from eth_account import Account

from djinn_validator.chain.line_registry import (
    PERMANENT_REVERT_MARKERS,
    TERMINAL_SUCCESS_MARKERS,
    LineOutcomeSubmitter,
    SubmitResult,
)


TEST_KEY = "0x" + "11" * 32
CHAIN_ID = 84532


def _submitter_with_send_raising(err_msg: str) -> LineOutcomeSubmitter:
    """Build a submitter whose underlying web3 call raises with err_msg.

    The error will fire inside _send_inside_lock at get_transaction_count
    (the first awaited RPC). The except-Exception classifier in submit()
    sees the message and labels it.
    """
    w3 = MagicMock()
    w3.to_checksum_address = lambda a: a if a.startswith("0x") else "0x" + a
    w3.eth.get_transaction_count = AsyncMock(side_effect=Exception(err_msg))
    # build_transaction is on a chain of mocks; not reached when get_tx_count raises.
    w3.eth.contract = MagicMock(return_value=MagicMock())

    sub = LineOutcomeSubmitter(
        w3=w3,
        registry_address="0x" + "C0DE" + "0" * 36,
        private_key_hex=TEST_KEY,
        chain_id=CHAIN_ID,
    )
    return sub


@pytest.mark.asyncio
async def test_already_finalized_human_name_terminal() -> None:
    sub = _submitter_with_send_raising("execution reverted: AlreadyFinalized")
    own_eoa = Account.from_key(TEST_KEY).address
    result = await sub.submit(
        line_hash=b"\x00" * 32, outcome=1, signers=[own_eoa], signatures=[b"\x00" * 65]
    )
    assert result.status == "already_finalized"
    assert result.is_terminal is True


@pytest.mark.asyncio
async def test_already_finalized_selector_terminal() -> None:
    """0x475a2535 is the keccak4 selector for AlreadyFinalized() — what
    web3.py reports in production."""
    sub = _submitter_with_send_raising("execution reverted: 0x475a2535")
    own_eoa = Account.from_key(TEST_KEY).address
    result = await sub.submit(
        line_hash=b"\x00" * 32, outcome=1, signers=[own_eoa], signatures=[b"\x00" * 65]
    )
    assert result.status == "already_finalized"
    assert result.is_terminal is True


@pytest.mark.asyncio
async def test_already_finalized_tuple_form_terminal() -> None:
    """Some web3.py versions surface the selector inside a Python tuple
    repr (matching the form recorded in /v1/diag/v1747's
    recent_submit_errors). Still must classify as terminal."""
    sub = _submitter_with_send_raising("('0x475a2535', '0x475a2535')")
    own_eoa = Account.from_key(TEST_KEY).address
    result = await sub.submit(
        line_hash=b"\x00" * 32, outcome=1, signers=[own_eoa], signatures=[b"\x00" * 65]
    )
    assert result.status == "already_finalized"
    assert result.is_terminal is True


@pytest.mark.asyncio
async def test_already_attested_selector_terminal() -> None:
    """0x35d90805 = AlreadyAttested(). Means own EOA already on chain for
    this lineHash — retrying would just re-revert. Treat as terminal-success
    so the caller stops resubmitting."""
    sub = _submitter_with_send_raising("execution reverted: 0x35d90805")
    own_eoa = Account.from_key(TEST_KEY).address
    result = await sub.submit(
        line_hash=b"\x00" * 32, outcome=1, signers=[own_eoa], signatures=[b"\x00" * 65]
    )
    assert result.status == "already_finalized"
    assert result.is_terminal is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selector,name",
    [
        ("0xc74a206d", "InvalidOutcome"),
        ("0x5cd5d233", "BadSignature"),
        ("0xf162cce5", "NotInValidatorSet"),
        ("0xff633a38", "LengthMismatch"),
        ("0xd92e233d", "ZeroAddress"),
    ],
)
async def test_permanent_revert_selectors_classified_permanent(
    selector: str, name: str
) -> None:
    """Each of the contract's non-recoverable errors must classify as
    permanent for both the selector and the human name forms."""
    own_eoa = Account.from_key(TEST_KEY).address
    for err_form in (
        f"execution reverted: {selector}",
        f"execution reverted: {name}",
    ):
        sub = _submitter_with_send_raising(err_form)
        result = await sub.submit(
            line_hash=b"\x00" * 32,
            outcome=1,
            signers=[own_eoa],
            signatures=[b"\x00" * 65],
        )
        assert result.status == "permanent", (err_form, result)
        assert result.is_terminal is False


@pytest.mark.asyncio
async def test_unknown_revert_classified_transient() -> None:
    """RPC flakes / gas underestimates / network errors fall through to
    transient and are retried."""
    sub = _submitter_with_send_raising("rpc error: connection reset by peer")
    own_eoa = Account.from_key(TEST_KEY).address
    result = await sub.submit(
        line_hash=b"\x00" * 32, outcome=1, signers=[own_eoa], signatures=[b"\x00" * 65]
    )
    assert result.status == "transient"
    assert result.is_terminal is False


def test_marker_constants_cover_every_contract_error() -> None:
    """Pin: every error declared in LineOutcomeRegistry.sol is in one of
    the marker tuples (selector + human form). New errors added to the
    contract must be added here too — otherwise their reverts silently
    fall through to 'transient' and burn gas in retry loops."""
    expected_terminal = {"AlreadyFinalized", "0x475a2535", "AlreadyAttested", "0x35d90805"}
    expected_permanent = {
        "InvalidOutcome", "0xc74a206d",
        "BadSignature", "0x5cd5d233",
        "NotInValidatorSet", "0xf162cce5",
        "LengthMismatch", "0xff633a38",
        "ZeroAddress", "0xd92e233d",
    }
    assert set(TERMINAL_SUCCESS_MARKERS) == expected_terminal
    assert set(PERMANENT_REVERT_MARKERS) == expected_permanent
