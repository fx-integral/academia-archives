import pytest
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from unittest.mock import (
    Mock,
    patch,
)

from subnet_validator.services.weight_calculator_service import (
    WeightCalculatorService,
)
from subnet_validator.database.entities import (
    Coupon,
    CouponStatus,
)


class TestWeightCalculatorService:
    def setup_method(self):
        self.mock_db = Mock()
        self.calculator = WeightCalculatorService(
            db=self.mock_db,
            coupon_weight=0.8,
            container_weight=0.2,
            delta_points=timedelta(days=7),
        )

    def test_calculate_coupon_points_less_than_7_days(self):
        """Test that coupons less than 7 days old get 100 points."""
        # Create a coupon created 3 days ago
        coupon = Mock()
        coupon.created_at = datetime.now(UTC) - timedelta(days=3)

        points = self.calculator.calculate_coupon_points(coupon)
        assert points == 100

    def test_calculate_coupon_points_7_days_or_more(self):
        """Test that coupons 7 days or older get 200 points."""
        # Create a coupon created 10 days ago
        coupon = Mock()
        coupon.created_at = datetime.now(UTC) - timedelta(days=10)

        points = self.calculator.calculate_coupon_points(coupon)
        assert points == 200

    def test_calculate_coupon_points_exactly_7_days(self):
        """Test that coupons exactly 7 days old get 200 points."""
        # Create a coupon created exactly 7 days ago
        coupon = Mock()
        coupon.created_at = datetime.now(UTC) - timedelta(days=7)

        points = self.calculator.calculate_coupon_points(coupon)
        assert points == 200

    def test_deduplicate_coupons_by_site_no_duplicates(self):
        """Test deduplication when there are no duplicates."""
        # Create test coupons
        coupon1 = Mock()
        coupon1.site_id = 1
        coupon1.code = "CODE1"
        coupon1.created_at = datetime.now(UTC) - timedelta(days=1)
        coupon1.miner_hotkey = "hotkey1"

        coupon2 = Mock()
        coupon2.site_id = 2
        coupon2.code = "CODE2"
        coupon2.created_at = datetime.now(UTC) - timedelta(days=2)
        coupon2.miner_hotkey = "hotkey2"

        coupons = [coupon1, coupon2]
        result = self.calculator.deduplicate_coupons_by_site(coupons)

        assert len(result) == 2
        assert coupon1 in result
        assert coupon2 in result

    def test_deduplicate_coupons_by_site_with_duplicates(self):
        """Test deduplication when there are duplicates."""
        # Create test coupons with duplicates
        coupon1 = Mock()
        coupon1.site_id = 1
        coupon1.code = "CODE1"
        coupon1.created_at = datetime.now(UTC) - timedelta(days=3)  # Earliest
        coupon1.miner_hotkey = "hotkey1"

        coupon2 = Mock()
        coupon2.site_id = 1
        coupon2.code = "CODE1"
        coupon2.created_at = datetime.now(UTC) - timedelta(days=1)  # Later
        coupon2.miner_hotkey = "hotkey2"

        coupon3 = Mock()
        coupon3.site_id = 1
        coupon3.code = "CODE1"
        coupon3.created_at = datetime.now(UTC) - timedelta(days=2)  # Middle
        coupon3.miner_hotkey = "hotkey3"

        coupons = [coupon1, coupon2, coupon3]
        result = self.calculator.deduplicate_coupons_by_site(coupons)

        assert len(result) == 1
        assert result[0] == coupon1  # Should keep the earliest one

    def test_calculate_miner_coupon_points(self):
        """Test calculation of total coupon points per miner."""
        # Create test coupons
        coupon1 = Mock()
        coupon1.miner_hotkey = "hotkey1"
        coupon1.created_at = datetime.now(UTC) - timedelta(
            days=3
        )  # 100 points

        coupon2 = Mock()
        coupon2.miner_hotkey = "hotkey1"
        coupon2.created_at = datetime.now(UTC) - timedelta(
            days=10
        )  # 200 points

        coupon3 = Mock()
        coupon3.miner_hotkey = "hotkey2"
        coupon3.created_at = datetime.now(UTC) - timedelta(
            days=8
        )  # 200 points

        coupons = [coupon1, coupon2, coupon3]
        result = self.calculator.calculate_miner_coupon_points(coupons)

        assert result["hotkey1"] == 300  # 100 + 200
        assert result["hotkey2"] == 200  # 200

    def test_calculate_normalized_scores(self):
        """Test normalized score calculation."""
        coupon_points = {
            "hotkey1": 1000,  # High coupon points
            "hotkey2": 300,  # Low coupon points
        }
        container_points = {
            "hotkey1": 200,  # Some container points
            "hotkey2": 100,  # Some container points
        }

        scores = self.calculator.calculate_normalized_scores(
            coupon_points, container_points
        )

        # hotkey1: (0.8 * 1000 + 0.2 * 200) / 840 = 840 / 840 = 1.0
        # hotkey2: (0.8 * 300 + 0.2 * 100) / 840 = 260 / 840 = 0.3095
        assert scores["hotkey1"] == 1.0
        assert round(scores["hotkey2"], 4) == 0.3095

    def test_calculate_normalized_scores_no_points(self):
        """Test normalized score calculation when no miners have points."""
        coupon_points = {}
        container_points = {}

        scores = self.calculator.calculate_normalized_scores(
            coupon_points, container_points
        )

        assert scores == {}

    def test_calculate_normalized_scores_zero_max_points(self):
        """Test normalized score calculation when max points is zero."""
        coupon_points = {"hotkey1": 0}
        container_points = {"hotkey1": 0}

        scores = self.calculator.calculate_normalized_scores(
            coupon_points, container_points
        )

        assert scores["hotkey1"] == 0.0

    def test_get_container_points_stubbed(self):
        """Test that container points are stubbed (return empty dict)."""
        result = self.calculator.get_container_points()
        assert result == {}

    def test_calculate_coupon_points_timezone_naive(self):
        """Test that timezone-naive datetimes are handled correctly."""
        # Create a coupon with timezone-naive datetime
        coupon = Mock()
        coupon.created_at = datetime.now(UTC).replace(
            tzinfo=None
        )  # Remove timezone info

        points = self.calculator.calculate_coupon_points(coupon)
        # Should still return 100 points for recent coupon
        assert points == 100
