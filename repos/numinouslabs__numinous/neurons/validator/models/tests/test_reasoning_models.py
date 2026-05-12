from datetime import datetime

import pytest

from neurons.validator.models.reasoning import (
    MAX_REASONING_CHARS,
    MISSING_REASONING_PREFIX,
    ReasoningModel,
)


class TestReasoningModel:
    def test_create_minimal(self):
        model = ReasoningModel(
            run_id="run001",
            reasoning="reasoning",
        )
        assert model.run_id == "run001"
        assert model.reasoning == "reasoning"

        # Defaults
        assert model.created_at is None
        assert model.updated_at is None
        assert model.exported is False

    def test_create_full(self):
        dt = datetime(2024, 1, 1, 12, 0)

        model = ReasoningModel(
            run_id="run002",
            reasoning="reasoning",
            created_at=dt,
            updated_at=dt,
            exported=True,
        )

        assert model.run_id == "run002"
        assert model.reasoning == "reasoning"
        assert model.created_at == dt
        assert model.updated_at == dt
        assert model.exported is True

    @pytest.mark.parametrize(
        "exported_input, expected",
        [
            (1, True),
            (0, False),
        ],
    )
    def test_exported_int_to_bool(self, exported_input, expected):
        model = ReasoningModel(
            run_id="run004",
            reasoning="reasoning",
            exported=exported_input,
        )
        assert model.exported is expected

    def test_exported_bool_passthrough(self):
        model = ReasoningModel(
            run_id="run005",
            reasoning="reasoning",
            exported=True,
        )
        assert model.exported is True

    def test_primary_key_property(self):
        model = ReasoningModel(
            run_id="run008",
            reasoning="reasoning",
        )
        assert model.primary_key == ["run_id"]

    def test_constants(self):
        assert MISSING_REASONING_PREFIX == "[NO_REASONING"
        assert MAX_REASONING_CHARS == 10_000
