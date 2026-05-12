from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import (
    List,
    Literal,
    Optional,
    Callable,
)
from sqlalchemy.orm import (
    Session,
)
from sqlalchemy import func
from pydantic import TypeAdapter

from subnet_validator.constants import CouponAction, SiteStatus
from subnet_validator.services.dynamic_config_service import (
    DynamicConfigService,
)
from subnet_validator.services.metagraph_service import MetagraphService
from subnet_validator.services.site_service import SiteService


from ..models import (
    CouponActionRequest,
    CouponDeleteRequest,
    CouponDeleteResponse,
    CouponRecheckRequest,
    CouponRecheckResponse,
    CouponSubmitRequest,
    CouponSubmitResponse,
    CouponResponse,
    CouponTypedActionRequest,
)

from ..database.entities import (
    Category,
    Coupon,
    CouponStatus,
    CouponActionLog,
    CouponOwnership,
)
from ..database.entities import (
    Site,
)
from ..auth import is_signature_valid
from ..models import CouponSubmitRequest

from fiber.logging_utils import get_logger


logger = get_logger(__name__)


class CouponService:
    def __init__(
        self,
        db: Session,
        dynamic_config_service: DynamicConfigService,
        site_service: SiteService,
        get_settings: Callable,
        metagraph,
    ):
        self.db = db
        self.dynamic_config_service = dynamic_config_service
        self.site_service = site_service
        self.get_settings = get_settings
        self.metagraph = metagraph

    @property
    def max_coupons_per_site_per_miner(self) -> int:
        """Get max coupons per site per miner from settings dynamically."""
        return self.get_settings().max_coupons_per_site_per_miner

    @property
    def recheck_interval(self) -> timedelta:
        """Get recheck interval from settings dynamically."""
        return self.get_settings().recheck_interval

    @property
    def resubmit_interval(self) -> timedelta:
        """Get resubmit interval from settings dynamically."""
        return self.get_settings().resubmit_interval

    @property
    def submit_window(self) -> timedelta:
        """Get submit window from settings dynamically."""
        return self.get_settings().submit_window

    def create_coupon(
        self,
        request: CouponSubmitRequest,
        signature: str,
        source_hotkey: str,
        from_sync: bool = False,
    ) -> CouponSubmitResponse:
        self._validate_submit_request(request, from_sync=from_sync)

        # Validate ownership before proceeding
        self._validate_ownership_before_creation(
            site_id=request.site_id,
            code=request.code,
            miner_hotkey=request.hotkey,
        )

        # Check if coupon already exists for this miner hotkey
        existing_coupon = (
            self.db.query(Coupon)
            .filter(
                func.lower(Coupon.code) == func.lower(request.code),
                Coupon.site_id == request.site_id,
                Coupon.miner_hotkey == request.hotkey,
            )
            .first()
        )

        if existing_coupon:
            # If recently deleted, block resubmission within the configured window
            if (
                existing_coupon.deleted_at is not None
                and existing_coupon.deleted_at.replace(tzinfo=UTC)
                > datetime.now(UTC) - self.resubmit_interval
            ):
                raise ValueError(
                    f"You cannot resubmit this coupon because it was deleted less than {int(self.resubmit_interval.total_seconds() / 3600)} hours ago.\n"
                    f"Please try again later (after {existing_coupon.deleted_at.replace(tzinfo=UTC) + self.resubmit_interval})."
                )

            # Update existing coupon in place; keep original created_at
            existing_coupon.category_id = request.category_id
            existing_coupon.discount_percentage = request.discount_percentage
            existing_coupon.discount_value = request.discount_value
            existing_coupon.valid_until = request.get_valid_until_datetime()
            existing_coupon.is_global = request.is_global
            existing_coupon.restrictions = request.restrictions
            existing_coupon.country_code = request.country_code
            existing_coupon.used_on_product_url = (
                request.used_on_product_url.unicode_string()
                if request.used_on_product_url
                else None
            )
            existing_coupon.source_hotkey = source_hotkey
            existing_coupon.deleted_at = None
            existing_coupon.status = CouponStatus.PENDING
            existing_coupon.last_action = CouponAction.CREATE
            existing_coupon.last_action_date = request.submitted_at
            existing_coupon.last_action_signature = signature
            existing_coupon.miner_coldkey = request.coldkey
            existing_coupon.use_coldkey_for_signature = (
                request.use_coldkey_for_signature
            )

            # Log action
            self._create_action_log(
                coupon=existing_coupon,
                action=CouponAction.CREATE,
                action_date=request.submitted_at,
                signature=signature,
                source_hotkey=source_hotkey,
            )

            # Ensure/update ownership for this coupon code on this site
            self._ensure_coupon_ownership(
                site_id=request.site_id,
                code=request.code,
                owner_hotkey=request.hotkey,
            )

            # Update available slots
            self.site_service.update_available_slots(request.site_id)

            self.db.commit()
            return CouponSubmitResponse(
                coupon_id=existing_coupon.id, is_new=False
            )
        else:
            # Create new coupon
            coupon = Coupon(
                code=request.code,
                site_id=request.site_id,
                category_id=request.category_id,
                discount_percentage=request.discount_percentage,
                discount_value=request.discount_value,
                valid_until=request.get_valid_until_datetime(),
                miner_hotkey=request.hotkey,
                is_global=request.is_global,
                restrictions=request.restrictions,
                country_code=request.country_code,
                used_on_product_url=(
                    request.used_on_product_url.unicode_string()
                    if request.used_on_product_url
                    else None
                ),
                source_hotkey=source_hotkey,
                created_at=request.get_submitted_at_datetime(),
                last_action=CouponAction.CREATE,
                last_action_date=request.submitted_at,
                last_action_signature=signature,
                miner_coldkey=request.coldkey,
                use_coldkey_for_signature=request.use_coldkey_for_signature,
            )

            self.db.add(coupon)

            # Log action
            self._create_action_log(
                coupon=coupon,
                action=CouponAction.CREATE,
                action_date=request.submitted_at,
                signature=signature,
                source_hotkey=source_hotkey,
            )

            # Update available slots
            self.site_service.update_available_slots(request.site_id)

            # Ensure/update ownership for this coupon code on this site
            self._ensure_coupon_ownership(
                site_id=request.site_id,
                code=request.code,
                owner_hotkey=request.hotkey,
            )

            self.db.commit()
            return CouponSubmitResponse(coupon_id=coupon.id, is_new=True)

    def get_coupons(
        self,
        miner_hotkey: Optional[str] = None,
        site_id: Optional[int] = None,
        updated_from: Optional[datetime] = None,
        created_from: Optional[datetime] = None,
        last_action_from: Optional[datetime] = None,
        status: Optional[CouponStatus] = None,
        last_checked_to: Optional[datetime] = None,
        page_size: int = 20,
        page_number: int = 1,
        sort_by: Literal[
            "created_at", "updated_at", "last_action_date"
        ] = "updated_at",
        bypass_submit_window: bool = False,
        site_status: Optional[SiteStatus] = None,
    ) -> List[Coupon]:
        """
        Get coupons with optional filtering by site status.
        
        Args:
            site_status: If provided, only return coupons from sites with this status.
                        If None, return coupons from all sites regardless of status.
        """
        if site_status is not None:
            query = self.db.query(Coupon).join(Site).filter(Site.status == site_status)
        else:
            query = self.db.query(Coupon)
            
        if not bypass_submit_window:
            query = query.filter(
                Coupon.last_action_date
                < int(
                    (datetime.now(UTC) - self.submit_window).timestamp() * 1000
                )
            )
        if miner_hotkey is not None:
            query = query.filter(Coupon.miner_hotkey == miner_hotkey)
        if site_id is not None:
            query = query.filter(Coupon.site_id == site_id)
        if updated_from is not None:
            query = query.filter(Coupon.updated_at > updated_from)
        if created_from is not None:
            query = query.filter(Coupon.created_at > created_from)
        if last_action_from is not None:
            query = query.filter(
                Coupon.last_action_date
                > int(last_action_from.timestamp() * 1000)
            )
        if status is not None:
            query = query.filter(Coupon.status == status)
        if last_checked_to is not None:
            query = query.filter(Coupon.last_checked_at < last_checked_to)
        # Pagination
        offset = (page_number - 1) * page_size
        coupons = (
            query.order_by(getattr(Coupon, sort_by).asc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return coupons


    def delete_coupon(
        self,
        request: CouponDeleteRequest,
        signature: str,
        from_sync: bool = False,
    ) -> CouponDeleteResponse:
        coupon = self._validate_delete_request(
            request, skip_submit_window_validation=from_sync
        )
        coupon.deleted_at = request.get_submitted_at_datetime()
        coupon.status = CouponStatus.DELETED
        coupon.last_action = CouponAction.DELETE
        coupon.last_action_date = request.submitted_at
        coupon.last_action_signature = signature
        # Log action
        self._create_action_log(
            coupon=coupon,
            action=CouponAction.DELETE,
            action_date=request.submitted_at,
            signature=signature,
            source_hotkey=coupon.source_hotkey,
        )

        # Clear ownership when coupon is deleted
        self._clear_coupon_ownership(
            site_id=request.site_id,
            code=request.code,
        )

        # Update available slots when coupon is deleted
        self.site_service.update_available_slots(request.site_id)

        self.db.commit()
        return CouponDeleteResponse(coupon_id=coupon.id)

    def recheck_coupon(
        self,
        request: CouponRecheckRequest,
        signature: str,
        from_sync: bool = False,
    ) -> CouponRecheckResponse:
        coupon = self._validate_recheck_request(
            request, skip_submit_window_validation=from_sync
        )
        coupon.status = CouponStatus.PENDING
        coupon.last_action = CouponAction.RECHECK
        coupon.last_action_date = request.submitted_at
        coupon.last_action_signature = signature
        # Log action
        self._create_action_log(
            coupon=coupon,
            action=CouponAction.RECHECK,
            action_date=request.submitted_at,
            signature=signature,
            source_hotkey=coupon.source_hotkey,
        )

        # Update available slots when coupon is rechecked
        self.site_service.update_available_slots(request.site_id)

        self.db.commit()
        return CouponRecheckResponse(coupon_id=coupon.id)

    def update_slots_for_site(self, site_id: int) -> None:
        """
        Update available slots for a site after coupon status changes.
        This should be called after validation tasks change coupon statuses.
        """
        self.site_service.update_available_slots(site_id)

    def handle_expired_coupons(self) -> None:
        """
        Mark expired coupons as EXPIRED and update slots for affected sites.
        This should be called periodically to free up slots from expired coupons.
        """
        from datetime import datetime, UTC

        now = datetime.now(UTC)
        expired_coupons = (
            self.db.query(Coupon)
            .filter(
                Coupon.valid_until < now,
                Coupon.status.in_([CouponStatus.PENDING, CouponStatus.VALID]),
                Coupon.deleted_at.is_(None),
            )
            .all()
        )

        if expired_coupons:
            logger.info(f"Found {len(expired_coupons)} expired coupons")

            # Group by site_id to update slots efficiently
            sites_to_update = set()
            for coupon in expired_coupons:
                coupon.status = CouponStatus.EXPIRED
                coupon.last_checked_at = now
                sites_to_update.add(coupon.site_id)

            # Update slots for affected sites
            for site_id in sites_to_update:
                self.site_service.update_available_slots(site_id)
                logger.info(f"Updated slots for site {site_id}")

            self.db.commit()
            logger.info(
                f"Marked {len(expired_coupons)} coupons as expired and updated slots"
            )

    def _create_action_log(
        self,
        coupon: Coupon,
        action: CouponAction,
        action_date: int,
        signature: str,
        source_hotkey: str,
    ) -> None:
        log = CouponActionLog(
            code=coupon.code,
            site_id=coupon.site_id,
            miner_hotkey=coupon.miner_hotkey,
            action=action,
            action_date=action_date,
            signature=signature,
            source_hotkey=source_hotkey,
        )
        self.db.add(log)

    def is_coupon_exists(
        self,
        site_id: int,
        code: str,
        miner_hotkey: str,
    ) -> bool:
        coupon = (
            self.db.query(Coupon)
            .filter(
                Coupon.site_id == site_id,
                func.lower(Coupon.code) == func.lower(code),
                Coupon.miner_hotkey == miner_hotkey,
            )
            .first()
        )
        return coupon is not None

    def sync_coupons_batch(
        self,
        coupons_data: List[CouponResponse],
        source_hotkey: str,
    ) -> List[CouponSubmitResponse]:
        """
        Simplified sync from another validator:
        - Create coupon if not exists (by site_id + miner_hotkey + code, case-insensitive)
        - If exists and incoming last_action_date is newer, update fields and status
        - No cross-validator duplicate resolution, IDs may differ across validators
        - Status mapping: DELETE -> DELETED, RECHECK/CREATE -> PENDING
        """
        responses = []

        for coupon_data in coupons_data:
            try:
                # Validate signature for each coupon
                if not self._validate_coupon_signature(coupon_data):
                    logger.warning(
                        f"Invalid signature for coupon {coupon_data.code} from {source_hotkey}"
                    )
                    continue

                # Check if coupon already exists for this miner hotkey
                existing_coupon = (
                    self.db.query(Coupon)
                    .filter(
                        func.lower(Coupon.code)
                        == func.lower(coupon_data.code),
                        Coupon.site_id == coupon_data.site_id,
                        Coupon.miner_hotkey == coupon_data.miner_hotkey,
                    )
                    .first()
                )

                if not existing_coupon:
                    # Validate ownership for sync before creating new coupon
                    if not self._validate_ownership_for_sync(
                        site_id=coupon_data.site_id,
                        code=coupon_data.code,
                        miner_hotkey=coupon_data.miner_hotkey,
                        action_date=coupon_data.last_action_date,
                    ):
                        logger.warning(
                            f"Skipping coupon {coupon_data.code} from {source_hotkey} due to ownership conflict"
                        )
                        continue

                    # New coupon from another validator
                    logger.debug(
                        f"Adding new coupon {coupon_data.code} from {source_hotkey}"
                    )

                    status = (
                        CouponStatus.DELETED
                        if coupon_data.last_action == CouponAction.DELETE
                        else CouponStatus.PENDING
                    )

                    coupon = Coupon(
                        created_at=coupon_data.created_at,
                        code=coupon_data.code,
                        site_id=coupon_data.site_id,
                        category_id=coupon_data.category_id,
                        discount_percentage=coupon_data.discount_percentage,
                        discount_value=coupon_data.discount_value,
                        valid_until=coupon_data.valid_until,
                        miner_hotkey=coupon_data.miner_hotkey,
                        is_global=coupon_data.is_global,
                        restrictions=coupon_data.restrictions,
                        country_code=coupon_data.country_code,
                        used_on_product_url=coupon_data.used_on_product_url,
                        source_hotkey=source_hotkey,
                        last_action=coupon_data.last_action,
                        last_action_date=coupon_data.last_action_date,
                        last_action_signature=coupon_data.last_action_signature,
                        deleted_at=coupon_data.deleted_at,
                        status=status,
                        miner_coldkey=coupon_data.miner_coldkey,
                        use_coldkey_for_signature=coupon_data.use_coldkey_for_signature,
                    )
                    self.db.add(coupon)
                    self.db.flush()
                    responses.append(
                        CouponSubmitResponse(coupon_id=coupon.id, is_new=True)
                    )
                else:
                    # Existing coupon: only update if incoming action is newer
                    if (
                        existing_coupon.last_action_date
                        < coupon_data.last_action_date
                    ):
                        # Validate ownership for sync before updating existing coupon
                        if not self._validate_ownership_for_sync(
                            site_id=coupon_data.site_id,
                            code=coupon_data.code,
                            miner_hotkey=coupon_data.miner_hotkey,
                            action_date=coupon_data.last_action_date,
                        ):
                            logger.warning(
                                f"Skipping update for coupon {coupon_data.code} from {source_hotkey} due to ownership conflict"
                            )
                            continue

                        logger.debug(
                            f"Updating existing coupon {coupon_data.code} with newer action from {source_hotkey}"
                        )

                        existing_coupon.category_id = coupon_data.category_id
                        existing_coupon.discount_percentage = (
                            coupon_data.discount_percentage
                        )
                        existing_coupon.discount_value = (
                            coupon_data.discount_value
                        )
                        existing_coupon.valid_until = coupon_data.valid_until
                        existing_coupon.is_global = coupon_data.is_global
                        existing_coupon.restrictions = coupon_data.restrictions
                        existing_coupon.source_hotkey = source_hotkey
                        existing_coupon.country_code = coupon_data.country_code
                        existing_coupon.used_on_product_url = (
                            coupon_data.used_on_product_url
                        )
                        existing_coupon.deleted_at = coupon_data.deleted_at
                        existing_coupon.last_action = coupon_data.last_action
                        existing_coupon.last_action_date = (
                            coupon_data.last_action_date
                        )
                        existing_coupon.last_action_signature = (
                            coupon_data.last_action_signature
                        )
                        existing_coupon.miner_coldkey = (
                            coupon_data.miner_coldkey
                        )
                        existing_coupon.use_coldkey_for_signature = (
                            coupon_data.use_coldkey_for_signature
                        )

                        # Update status based on last action
                        existing_coupon.status = (
                            CouponStatus.DELETED
                            if coupon_data.last_action == CouponAction.DELETE
                            else CouponStatus.PENDING
                        )
                        responses.append(
                            CouponSubmitResponse(
                                coupon_id=existing_coupon.id, is_new=False
                            )
                        )
                        # Ensure/update ownership on newer action from sync
                        self._ensure_coupon_ownership(
                            site_id=coupon_data.site_id,
                            code=coupon_data.code,
                            owner_hotkey=coupon_data.miner_hotkey,
                        )
                    else:
                        logger.debug(
                            f"Skipping coupon {coupon_data.code} from {source_hotkey} because existing is as recent or newer"
                        )

            except Exception as e:
                # Log error but continue with other coupons
                logger.error(
                    f"Error syncing coupon {coupon_data.code}: {e}",
                    exc_info=True,
                )
                continue

        self.db.commit()
        return responses

    # Removed internal sync handlers in favor of calling public methods

    def _vaidate_base_request(
        self,
        request: CouponActionRequest,
        from_sync: bool = False,
    ) -> None:
        now = int(datetime.now(UTC).timestamp() * 1000)
        window_start = now - int(self.submit_window.total_seconds() * 1000)
        if not from_sync and (
            request.submitted_at < window_start or request.submitted_at >= now
        ):
            raise ValueError(
                f"Coupon was submitted outside the allowed {int(self.submit_window.total_seconds() / 60)}-minute time window."
            )
        if not from_sync:
            # Check if miner hotkey exists in metagraph
            miner_node = self.metagraph.get_node_by_hotkey(request.hotkey)
            if not miner_node or miner_node.is_validator:
                raise ValueError(
                    f"Miner hotkey {request.hotkey} does not registered in subnet."
                )
            if request.coldkey and miner_node.coldkey != request.coldkey:
                raise ValueError(
                    f"Miner coldkey {request.coldkey} does not match the coldkey in the metagraph for hotkey {request.hotkey}."
                )
            sync_progress = self.dynamic_config_service.get_sync_progress()
            if sync_progress:
                raise ValueError(
                    f"Coupon submission is disabled. Please try again later."
                )

        site = self.db.query(Site).filter(Site.id == request.site_id).first()
        if not site:
            raise ValueError(f"Site with id {request.site_id} does not exist.")

        if site.status == SiteStatus.INACTIVE:
            raise ValueError(
                f'Unable to validate the coupon "{request.code}" because the website {site.base_url} is currently marked as inactive.'
            )

    def _validate_recheck_request(
        self,
        request: CouponRecheckRequest,
        skip_submit_window_validation: bool = False,
    ) -> Coupon:
        self._vaidate_base_request(request, skip_submit_window_validation)

        # Check if site has available slots for potential resubmission
        if not self.site_service.can_submit_coupon(request.site_id):
            raise ValueError(
                f"Cannot recheck coupon because site {request.site_id} has no available slots. "
                f"Please wait for slots to become available before requesting revalidation."
            )

        coupon = (
            self.db.query(Coupon)
            .filter(
                func.lower(Coupon.code) == func.lower(request.code),
                Coupon.site_id == request.site_id,
                Coupon.miner_hotkey == request.hotkey,
            )
            .first()
        )

        if not coupon:
            raise ValueError(f'Coupon code "{request.code}" does not exist.')

        if coupon.deleted_at is not None:
            raise ValueError(
                f'The coupon "{request.code}" seems to be deleted by owner.'
            )

        if coupon.status != CouponStatus.INVALID:
            raise ValueError(
                f'You can only recheck invalid coupons. Coupon code "{request.code}" is not invalid.'
            )

        if (
            coupon.last_checked_at is not None
            and coupon.last_checked_at.replace(tzinfo=UTC)
            > datetime.now(UTC) - self.recheck_interval
        ):
            next_check_time = (
                coupon.last_checked_at.replace(tzinfo=UTC)
                + self.recheck_interval
            )
            raise ValueError(
                f"You can request code re-validation only once every {int(self.recheck_interval.total_seconds() / 3600)} hours.\n"
                f"Please try again later (after {next_check_time})."
            )

        return coupon

    def _validate_delete_request(
        self,
        request: CouponDeleteRequest,
        skip_submit_window_validation: bool = False,
    ) -> Coupon:
        # 1. Validate base request
        self._vaidate_base_request(request, skip_submit_window_validation)

        # 2. Check if coupon code exists and is not deleted
        coupon = (
            self.db.query(Coupon)
            .filter(
                func.lower(Coupon.code) == func.lower(request.code),
                Coupon.site_id == request.site_id,
                Coupon.miner_hotkey == request.hotkey,
            )
            .first()
        )
        if not coupon:
            raise ValueError(f'Coupon code "{request.code}" does not exist.')
        if coupon.deleted_at is not None:
            raise ValueError(
                f'Coupon code "{request.code}" has already been deleted.'
            )
        return coupon

    def _validate_submit_request(
        self,
        request: CouponSubmitRequest,
        from_sync: bool = False,
    ) -> None:
        # 1. Validate base request
        self._vaidate_base_request(request, from_sync=from_sync)

        site = self.db.query(Site).filter(Site.id == request.site_id).first()
        if request.used_on_product_url:
            url_host = (
                request.used_on_product_url.unicode_host().lower().rstrip(".")
            )
            base_host = (site.base_url or "").lower().rstrip(".")
            if not (
                url_host == base_host or url_host.endswith("." + base_host)
            ):
                raise ValueError(
                    f"Used on product URL {request.used_on_product_url} is not valid for site {site.base_url}."
                )

        # 2. Check if category exists if provided
        if request.category_id:
            category = (
                self.db.query(Category)
                .filter(Category.id == request.category_id)
                .first()
            )
            if not category:
                raise ValueError(
                    f"Category with id {request.category_id} does not exist."
                )
        # 3. Check if coupon code already exists and not deleted
        coupon = (
            self.db.query(Coupon)
            .filter(
                func.lower(Coupon.code) == func.lower(request.code),
                Coupon.deleted_at == None,
                Coupon.site_id == request.site_id,
            )
            .first()
        )
        if coupon:
            raise ValueError(f'Coupon code "{request.code}" already exists.')
        # 4. Check if site has available slots for new coupons
        if not self.site_service.can_submit_coupon(request.site_id):
            raise ValueError(
                f"Site with id {request.site_id} has no available slots for new coupons. Please try again later when slots become available."
            )

        # 5. Check if miner has reached the per-miner limit for this site
        miner_coupons = (
            self.db.query(Coupon)
            .filter(
                Coupon.site_id == request.site_id,
                Coupon.miner_hotkey == request.hotkey,
                Coupon.deleted_at.is_(None),
            )
            .count()
        )
        if miner_coupons >= self.max_coupons_per_site_per_miner:
            raise ValueError(
                f"You have reached the maximum limit of {self.max_coupons_per_site_per_miner} coupons per site. "
                f"Please delete some existing coupons before submitting new ones."
            )

    def _validate_coupon_signature(
        self,
        coupon_data: CouponResponse,
    ) -> bool:
        """
        Validate the signature of a coupon from another validator.
        Returns True if signature is valid, False otherwise.
        """
        try:
            typed_coupon_data = CouponTypedActionRequest(
                hotkey=coupon_data.miner_hotkey,
                site_id=coupon_data.site_id,
                code=coupon_data.code,
                submitted_at=coupon_data.last_action_date,
                action=coupon_data.last_action,
                coldkey=coupon_data.miner_coldkey,
                use_coldkey_for_signature=coupon_data.use_coldkey_for_signature,
            )
            return is_signature_valid(
                typed_coupon_data, coupon_data.last_action_signature
            )
        except Exception:
            return False

    def _clear_coupon_ownership(
        self,
        site_id: int,
        code: str,
    ) -> None:
        """Clear ownership when coupon is deleted by miner."""
        ownership = (
            self.db.query(CouponOwnership)
            .filter(
                CouponOwnership.site_id == site_id,
                func.lower(CouponOwnership.code) == func.lower(code),
            )
            .first()
        )
        if ownership:
            # Clear the owner_hotkey but keep the record for debugging/audit purposes
            ownership.owner_hotkey = None
            ownership.updated_at = datetime.now(UTC)

    def _validate_ownership_before_creation(
        self,
        site_id: int,
        code: str,
        miner_hotkey: str,
    ) -> None:
        """Validate that the miner can claim ownership of this coupon code."""
        ownership = (
            self.db.query(CouponOwnership)
            .filter(
                CouponOwnership.site_id == site_id,
                func.lower(CouponOwnership.code) == func.lower(code),
            )
            .first()
        )

        if (
            ownership
            and ownership.owner_hotkey is not None
            and ownership.owner_hotkey != miner_hotkey
        ):
            raise ValueError(
                f"Coupon code '{code}' is already owned by another miner. "
                f"Only the current owner can create/update this coupon."
            )

    def _validate_ownership_for_sync(
        self,
        site_id: int,
        code: str,
        miner_hotkey: str,
        action_date: int,
    ) -> bool:
        """
        Validate ownership for sync operations.
        Returns True if the miner can claim ownership, False if blocked by existing ownership.
        For sync, we allow ownership transfer if the action is newer.
        """
        ownership = (
            self.db.query(CouponOwnership)
            .filter(
                CouponOwnership.site_id == site_id,
                func.lower(CouponOwnership.code) == func.lower(code),
            )
            .first()
        )

        if not ownership:
            return True  # No existing ownership, can claim

        if ownership.owner_hotkey is None:
            return True  # Ownership was cleared, can claim

        if ownership.owner_hotkey == miner_hotkey:
            return True  # Already owned by this miner

        # Check if this is a newer action that should transfer ownership
        # For now, we'll be permissive and allow sync to update ownership
        # This could be enhanced with more sophisticated conflict resolution
        return True

    def _ensure_coupon_ownership(
        self,
        site_id: int,
        code: str,
        owner_hotkey: str,
    ) -> None:
        """
        Ensure there is a `CouponOwnership` record for (site_id, code).
        - If none exists, create it and set owner to the provided hotkey.
        - If exists with cleared ownership (owner_hotkey is None), update it with new owner.
        - If exists with different owner, record a contest.
        """
        ownership = (
            self.db.query(CouponOwnership)
            .filter(
                CouponOwnership.site_id == site_id,
                func.lower(CouponOwnership.code) == func.lower(code),
            )
            .first()
        )

        now_dt = datetime.now(UTC)
        if not ownership:
            ownership = CouponOwnership(
                site_id=site_id,
                code=code,
                owner_hotkey=owner_hotkey,
                acquired_at=now_dt,
            )
            self.db.add(ownership)
            return

        if ownership.owner_hotkey is None:
            # Ownership was cleared, update with new owner
            ownership.owner_hotkey = owner_hotkey
            ownership.acquired_at = now_dt
            ownership.updated_at = now_dt
            return

        if ownership.owner_hotkey != owner_hotkey:
            # Another miner attempts to use the same code for the site — mark as contested
            ownership.last_contested_at = now_dt
            ownership.contest_count = (ownership.contest_count or 0) + 1

    def can_process_recheck(self, site_id: int) -> bool:
        """
        Check if a site can process coupon rechecks.
        Returns True if there are available slots for potential resubmission, False otherwise.
        """
        return self.site_service.can_submit_coupon(site_id)

    def can_miner_submit_to_site(
        self, miner_hotkey: str, site_id: int
    ) -> bool:
        """
        Check if a specific miner can submit more coupons to a specific site.
        Returns True if the miner is under the per-miner limit, False otherwise.
        """
        miner_coupons = (
            self.db.query(Coupon)
            .filter(
                Coupon.site_id == site_id,
                Coupon.miner_hotkey == miner_hotkey,
                Coupon.deleted_at.is_(None),
            )
            .count()
        )
        return miner_coupons < self.max_coupons_per_site_per_miner

    def get_miner_coupon_count(self, miner_hotkey: str, site_id: int) -> int:
        """
        Get the current number of active coupons for a specific miner on a specific site.
        """
        return (
            self.db.query(Coupon)
            .filter(
                Coupon.site_id == site_id,
                Coupon.miner_hotkey == miner_hotkey,
                Coupon.deleted_at.is_(None),
            )
            .count()
        )
