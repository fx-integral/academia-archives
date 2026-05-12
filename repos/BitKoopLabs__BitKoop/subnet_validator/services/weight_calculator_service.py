from datetime import (
    UTC,
    timedelta,
)
from typing import (
    Dict,
    List,
    Tuple,
    Callable,
)
from sqlalchemy import (
    and_,
)
from sqlalchemy.orm import (
    Session,
)

from ..database.entities import (
    Coupon,
    CouponStatus,
)
from fiber.logging_utils import (
    get_logger,
)

logger = get_logger(__name__)


class WeightCalculatorService:
    def __init__(
        self,
        db: Session,
        get_settings: Callable,
    ):
        self.db = db
        self.get_settings = get_settings

    @property
    def coupon_weight(self) -> float:
        """Get coupon weight from settings dynamically."""
        return self.get_settings().coupon_weight

    @property
    def container_weight(self) -> float:
        """Get container weight from settings dynamically."""
        return self.get_settings().container_weight

    @property
    def delta_points(self) -> timedelta:
        """Get delta points from settings dynamically."""
        return self.get_settings().delta_points

    def calculate_coupon_points(self, coupon: Coupon) -> int:
        """
        Award a flat 100 points per valid coupon.
        """
        return 100

    def get_valid_coupons(self) -> List[Coupon]:
        """
        Get all valid coupons
        """

        return (
            self.db.query(Coupon)
            .filter(
                and_(
                    Coupon.status == CouponStatus.VALID,
                    Coupon.deleted_at.is_(None),  # Not deleted
                )
            )
            .all()
        )

    def deduplicate_coupons_by_site(
        self, coupons: List[Coupon]
    ) -> List[Coupon]:
        """
        Group coupons by site and code, keeping only the earliest one for each duplicate.
        """
        # Group by site_id and code
        grouped_coupons: Dict[Tuple[int, str], List[Coupon]] = {}

        for coupon in coupons:
            key = (coupon.site_id, coupon.code)
            if key not in grouped_coupons:
                grouped_coupons[key] = []
            grouped_coupons[key].append(coupon)

        # For each group, keep only the earliest coupon
        deduplicated_coupons = []
        for key, coupon_list in grouped_coupons.items():
            if len(coupon_list) == 1:
                # No duplicates, keep as is
                deduplicated_coupons.append(coupon_list[0])
            else:
                # Multiple coupons with same code on same site, keep earliest
                # Handle timezone-aware and timezone-naive datetimes for comparison
                def get_created_at_for_comparison(coupon):
                    created_at = coupon.created_at
                    if created_at.tzinfo is None:
                        # If created_at is timezone-naive, assume it's in UTC
                        return created_at.replace(tzinfo=UTC)
                    return created_at

                earliest_coupon = min(
                    coupon_list, key=lambda c: get_created_at_for_comparison(c)
                )
                deduplicated_coupons.append(earliest_coupon)
                logger.info(
                    f"Found {len(coupon_list)} duplicate coupons for site {key[0]}, "
                    f"code {key[1]}. Keeping earliest from {earliest_coupon.miner_hotkey} "
                    f"created at {earliest_coupon.created_at}"
                )

        return deduplicated_coupons

    def calculate_miner_coupon_points(
        self, coupons: List[Coupon]
    ) -> Dict[str, int]:
        """
        Calculate total coupon points for each miner.
        """
        miner_points: Dict[str, int] = {}

        for coupon in coupons:
            points = self.calculate_coupon_points(coupon)
            miner_hotkey = coupon.miner_hotkey

            if miner_hotkey not in miner_points:
                miner_points[miner_hotkey] = 0
            miner_points[miner_hotkey] += points

        return miner_points

    def get_container_points(self) -> Dict[str, int]:
        """
        Stubbed container points calculation.
        TODO: Implement actual container scoring logic
        """
        # For now, return empty dict - no container points
        return {}

    def calculate_normalized_scores(
        self,
        coupon_points: Dict[str, int],
        container_points: Dict[str, int],
    ) -> Dict[str, float]:
        """
        Calculate normalized scores using the Bittensor Yuma Scoring Formula.
        score = min(1.0, round((0.8 * coupon_points + 0.2 * container_points) / MAX_POINTS, 4))
        """
        # Get all unique miners
        all_miners = set(coupon_points.keys()) | set(container_points.keys())

        if not all_miners:
            return {}

        # Calculate total points for each miner
        total_points: Dict[str, float] = {}
        for miner in all_miners:
            coupon_pts = coupon_points.get(miner, 0)
            container_pts = container_points.get(miner, 0)
            total_points[miner] = (
                self.coupon_weight * coupon_pts
                + self.container_weight * container_pts
            )

        # Find MAX_POINTS (highest total score)
        max_points = max(total_points.values()) if total_points else 0

        if max_points == 0:
            return {miner: 0.0 for miner in all_miners}

        # Calculate normalized scores
        scores: Dict[str, float] = {}
        for miner in all_miners:
            score = min(1.0, round(total_points[miner] / max_points, 4))
            scores[miner] = score

        return scores

    def log_scoring_summary(
        self,
        coupon_points: Dict[str, int],
        container_points: Dict[str, int],
        scores: Dict[str, float],
    ) -> None:
        """
        Log a summary of the scoring results.
        """
        logger.info("=== Weight Calculation Summary ===")
        logger.info(f"Total miners with coupon points: {len(coupon_points)}")
        logger.info(
            f"Total miners with container points: {len(container_points)}"
        )
        logger.info(f"Total miners with final scores: {len(scores)}")

        if scores:
            max_score = max(scores.values())
            min_score = min(scores.values())
            avg_score = sum(scores.values()) / len(scores)

            logger.info(f"Score range: {min_score:.4f} - {max_score:.4f}")
            logger.info(f"Average score: {avg_score:.4f}")

            # Log top 5 miners
            top_miners = sorted(
                scores.items(), key=lambda x: x[1], reverse=True
            )[:5]
            logger.info("Top 5 miners by score:")
            for i, (miner, score) in enumerate(top_miners, 1):
                coupon_pts = coupon_points.get(miner, 0)
                container_pts = container_points.get(miner, 0)
                logger.info(
                    f"  {i}. {miner}: {score:.4f} "
                    f"(coupons: {coupon_pts}, containers: {container_pts})"
                )

    def calculate_weights(self) -> Dict[str, float]:
        """
        Main method to calculate weights for all miners.
        Returns a dictionary mapping miner hotkeys to their normalized scores.
        """
        logger.info("Starting weight calculation...")

        try:
            # Get valid coupons
            logger.info("Fetching valid coupons...")
            valid_coupons = self.get_valid_coupons()
            logger.info(f"Found {len(valid_coupons)} valid coupons")

            # Deduplicate coupons by site and code
            logger.info("Deduplicating coupons by site and code...")
            deduplicated_coupons = self.deduplicate_coupons_by_site(
                valid_coupons
            )
            logger.info(
                f"After deduplication: {len(deduplicated_coupons)} coupons"
            )

            # Calculate coupon points for each miner
            logger.info("Calculating coupon points...")
            coupon_points = self.calculate_miner_coupon_points(
                deduplicated_coupons
            )
            logger.info(f"Calculated points for {len(coupon_points)} miners")

            # Get container points (stubbed for now)
            logger.info("Calculating container points...")
            container_points = self.get_container_points()
            logger.info(
                f"Calculated container points for {len(container_points)} miners"
            )

            # Calculate normalized scores
            logger.info("Calculating normalized scores...")
            scores = self.calculate_normalized_scores(
                coupon_points, container_points
            )

            # Log summary
            self.log_scoring_summary(coupon_points, container_points, scores)

            logger.info("Weight calculation completed successfully")

            return scores

        except Exception as e:
            logger.error(
                f"Error during weight calculation: {e}", exc_info=True
            )
            raise
