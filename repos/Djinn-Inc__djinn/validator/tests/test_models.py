"""Tests for Pydantic request/response model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from djinn_validator.api.models import (
    AnalyticsRequest,
    MPCInitRequest,
    MPCResultRequest,
    MPCRound1Request,
    OutcomeRequest,
    PurchaseRequest,
    RegisterSignalRequest,
)

VALID_ETH_ADDR = "0x" + "a1" * 20  # Valid 40-hex-char Ethereum address
SAMPLE_LINES_10 = [
    "Lakers -3.5 (-110)",
    "Celtics +3.5 (-110)",
    "Over 218.5 (-110)",
    "Under 218.5 (-110)",
    "Lakers ML (-150)",
    "Celtics ML (+130)",
    "Lakers -1.5 (-105)",
    "Celtics +1.5 (-115)",
    "Over 215.0 (-110)",
    "Under 215.0 (-110)",
]


# TestStoreShareRequest class removed 2026-05-04: legacy /v1/signal
# endpoint + StoreShareRequest model deleted. Bundle endpoint validation
# is covered by tests/test_share_bundle.py + StoreShareBundleRequest
# pydantic constraints in models.py.


class TestPurchaseRequest:
    def test_valid_request(self) -> None:
        req = PurchaseRequest(
            buyer_address=VALID_ETH_ADDR,
            sportsbook="draftkings",
            available_indices=[1, 3, 5],
        )
        assert len(req.available_indices) == 3

    def test_empty_available_indices(self) -> None:
        with pytest.raises(ValidationError, match="available_indices"):
            PurchaseRequest(
                buyer_address=VALID_ETH_ADDR,
                sportsbook="draftkings",
                available_indices=[],
            )

    def test_too_many_available_indices(self) -> None:
        with pytest.raises(ValidationError, match="available_indices"):
            PurchaseRequest(
                buyer_address=VALID_ETH_ADDR,
                sportsbook="draftkings",
                available_indices=list(range(1, 2002)),  # 2001 items
            )

    def test_index_out_of_range_zero(self) -> None:
        with pytest.raises(ValidationError, match="1-2000"):
            PurchaseRequest(
                buyer_address=VALID_ETH_ADDR,
                sportsbook="draftkings",
                available_indices=[0],
            )

    def test_index_out_of_range_high(self) -> None:
        with pytest.raises(ValidationError, match="1-2000"):
            PurchaseRequest(
                buyer_address=VALID_ETH_ADDR,
                sportsbook="draftkings",
                available_indices=[2001],
            )

    def test_index_boundary_values(self) -> None:
        req = PurchaseRequest(
            buyer_address=VALID_ETH_ADDR,
            sportsbook="draftkings",
            available_indices=[1, 2000],
        )
        assert req.available_indices == [1, 2000]

    def test_duplicate_indices_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            PurchaseRequest(
                buyer_address=VALID_ETH_ADDR,
                sportsbook="draftkings",
                available_indices=[3, 3, 5],
            )

    def test_invalid_buyer_address_format(self) -> None:
        with pytest.raises(ValidationError, match="Ethereum"):
            PurchaseRequest(
                buyer_address="not-an-address",
                sportsbook="draftkings",
                available_indices=[1],
            )

    def test_valid_buyer_address(self) -> None:
        req = PurchaseRequest(
            buyer_address="0x" + "ab" * 20,
            sportsbook="draftkings",
            available_indices=[1],
        )
        assert req.buyer_address == "0x" + "ab" * 20


class TestEventIdValidation:
    def test_valid_event_id_in_outcome(self) -> None:
        req = OutcomeRequest(
            signal_id="sig-1",
            event_id="abc123_def-456:789.0",
            outcome=1,
            validator_hotkey="hk1",
        )
        assert req.event_id == "abc123_def-456:789.0"

    def test_invalid_event_id_in_outcome(self) -> None:
        with pytest.raises(ValidationError):
            OutcomeRequest(
                signal_id="sig-1",
                event_id="ev id with spaces!",
                outcome=1,
                validator_hotkey="hk1",
            )

    def test_invalid_event_id_in_register(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="nba",
                event_id="<script>alert(1)</script>",
                home_team="A",
                away_team="B",
                lines=SAMPLE_LINES_10,
            )


class TestMPCRound1Request:
    def test_valid_hex_values(self) -> None:
        req = MPCRound1Request(
            session_id="s-1",
            gate_idx=0,
            validator_x=1,
            d_value="0xabcdef",
            e_value="ff00ff",
        )
        assert req.d_value == "0xabcdef"

    def test_invalid_d_value(self) -> None:
        with pytest.raises(ValidationError, match="hex"):
            MPCRound1Request(
                session_id="s-1",
                gate_idx=0,
                validator_x=1,
                d_value="not_hex!",
                e_value="ff00ff",
            )


class TestAnalyticsRequest:
    def test_default_data(self) -> None:
        req = AnalyticsRequest(event_type="purchase")
        assert req.data == {}

    def test_with_data(self) -> None:
        req = AnalyticsRequest(event_type="click", data={"page": "/signals"})
        assert req.data["page"] == "/signals"

    def test_event_type_too_long(self) -> None:
        with pytest.raises(ValidationError):
            AnalyticsRequest(event_type="x" * 200)

    def test_data_dict_too_many_keys(self) -> None:
        big_data = {f"key_{i}": i for i in range(51)}
        with pytest.raises(ValidationError, match="at most 50"):
            AnalyticsRequest(event_type="test", data=big_data)

    def test_data_dict_at_limit(self) -> None:
        data = {f"key_{i}": i for i in range(50)}
        req = AnalyticsRequest(event_type="test", data=data)
        assert len(req.data) == 50


class TestRegisterSignalSportValidation:
    def test_valid_sport_key(self) -> None:
        req = RegisterSignalRequest(
            sport="basketball_nba",
            event_id="ev-1",
            home_team="A",
            away_team="B",
            lines=SAMPLE_LINES_10,
        )
        assert req.sport == "basketball_nba"

    def test_sport_rejects_uppercase(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="Basketball_NBA",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=SAMPLE_LINES_10,
            )

    def test_sport_rejects_special_chars(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="nba; DROP TABLE",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=SAMPLE_LINES_10,
            )

    def test_sport_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=SAMPLE_LINES_10,
            )


class TestStringLengthLimits:
    """Verify max_length constraints on all string fields."""

    def test_signal_id_too_long(self) -> None:
        # Cover signal_id max_length on StoreShareBundleRequest, which
        # carries the same constraint that StoreShareRequest used to test
        # (StoreShareRequest was removed 2026-05-04).
        from djinn_validator.api.models import StoreShareBundleRequest, ShareBundleEntry

        valid_entry = ShareBundleEntry(
            target_address="0x" + "ab" * 20,
            share_x=1,
            share_ciphertext="aabb",
            index_ciphertext="ccdd",
        )
        with pytest.raises(ValidationError, match="signal_id"):
            StoreShareBundleRequest(
                signal_id="x" * 300,
                genius_address="0x" + "ab" * 20,
                shamir_threshold=2,
                bundle=[valid_entry],
            )

    def test_buyer_address_too_long(self) -> None:
        with pytest.raises(ValidationError):
            PurchaseRequest(
                buyer_address="x" * 300,
                sportsbook="dk",
                available_indices=[1],
            )

    def test_outcome_validator_hotkey_too_long(self) -> None:
        with pytest.raises(ValidationError):
            OutcomeRequest(
                signal_id="sig-1",
                event_id="ev-1",
                outcome=1,
                validator_hotkey="x" * 300,
            )

    def test_register_line_too_long(self) -> None:
        long_lines = SAMPLE_LINES_10.copy()
        long_lines[0] = "x" * 600
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="nba",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=long_lines,
            )

    def test_register_wrong_line_count(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="basketball_nba",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=["Lakers -3.5 (-110)"],
            )

    def test_mpc_d_value_too_long(self) -> None:
        with pytest.raises(ValidationError):
            MPCRound1Request(
                session_id="s-1",
                gate_idx=0,
                validator_x=1,
                d_value="a" * 300,
                e_value="ff",
            )


class TestMPCBoundsValidation:
    """Verify bounds on MPC numeric fields."""

    def test_coordinator_x_too_low(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=0,
                participant_xs=[1, 2],
            )

    def test_coordinator_x_too_high(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=256,
                participant_xs=[1, 2],
            )

    def test_gate_idx_bounds(self) -> None:
        with pytest.raises(ValidationError):
            MPCRound1Request(
                session_id="s-1",
                gate_idx=-1,
                validator_x=1,
                d_value="ab",
                e_value="cd",
            )

    def test_participating_validators_bounds(self) -> None:
        with pytest.raises(ValidationError):
            MPCResultRequest(
                session_id="s-1",
                signal_id="sig-1",
                available=True,
                participating_validators=-1,
            )

    def test_threshold_bounds(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=1,
                participant_xs=[1, 2],
                threshold=0,
            )

    def test_participant_xs_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=1,
                participant_xs=[0, 2],  # 0 is out of range
            )

    def test_participant_xs_too_high(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=1,
                participant_xs=[1, 256],  # 256 is out of range
            )

    def test_participant_xs_duplicates_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[1],
                coordinator_x=1,
                participant_xs=[1, 1, 2],  # duplicate
            )

    def test_mpc_available_indices_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[0],  # 0 is out of range
                coordinator_x=1,
                participant_xs=[1, 2],
            )

    def test_mpc_available_indices_too_high(self) -> None:
        with pytest.raises(ValidationError):
            MPCInitRequest(
                session_id="s-1",
                signal_id="sig-1",
                available_indices=[2001],  # 2001 is out of range
                coordinator_x=1,
                participant_xs=[1, 2],
            )


class TestRegisterSignalGameDate:
    """v1676 (P1-36): client-provided game_date for deterministic ESPN lookup.

    Without game_date, OutcomeAttestor walks back 30 days searching team-name
    matches in ESPN scoreboards. Different validators may match different
    historical games → divergent outcome lists → divergent scoreHashes →
    no quorum. Client passing the actual game_date eliminates the back-walk.
    """

    def test_game_date_optional(self) -> None:
        """Default None preserves backward compatibility with pre-v1676 clients."""
        req = RegisterSignalRequest(
            sport="baseball_mlb",
            event_id="ev-1",
            home_team="A",
            away_team="B",
            lines=SAMPLE_LINES_10,
        )
        assert req.game_date is None

    def test_game_date_yyyymmdd(self) -> None:
        req = RegisterSignalRequest(
            sport="baseball_mlb",
            event_id="ev-1",
            home_team="A",
            away_team="B",
            lines=SAMPLE_LINES_10,
            game_date="20260501",
        )
        assert req.game_date == "20260501"

    def test_game_date_empty_string_accepted(self) -> None:
        """Empty string is allowed (treated as None server-side)."""
        req = RegisterSignalRequest(
            sport="baseball_mlb",
            event_id="ev-1",
            home_team="A",
            away_team="B",
            lines=SAMPLE_LINES_10,
            game_date="",
        )
        assert req.game_date == ""

    def test_game_date_rejects_invalid_format(self) -> None:
        """Non-YYYYMMDD shapes rejected at model validation.

        We only validate shape (8 digits) at the model layer. Semantic invalid
        dates like "20261301" (month 13) pass the regex; ESPN simply returns no
        match and the attestor falls back to back-walk (pre-v1676 behavior).
        """
        for bad in ["2026-05-01", "5/1/2026", "abc", "20260", "20260501a"]:
            with pytest.raises(ValidationError):
                RegisterSignalRequest(
                    sport="baseball_mlb",
                    event_id="ev-1",
                    home_team="A",
                    away_team="B",
                    lines=SAMPLE_LINES_10,
                    game_date=bad,
                )

    def test_game_date_rejects_too_long(self) -> None:
        with pytest.raises(ValidationError):
            RegisterSignalRequest(
                sport="baseball_mlb",
                event_id="ev-1",
                home_team="A",
                away_team="B",
                lines=SAMPLE_LINES_10,
                game_date="2026050100",  # 10 chars, max 8
            )
