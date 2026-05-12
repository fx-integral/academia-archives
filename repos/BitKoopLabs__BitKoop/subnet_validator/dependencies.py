from functools import lru_cache
from pathlib import Path
from typing import (
    Annotated,
)
from datetime import (
    timedelta,
)

from fastapi import (
    Depends,
)
from subnet_validator.services.validator.api_coupon_validator import (
    ApiCouponValidator,
)

from subnet_validator.database.entities import Site
from subnet_validator.services.category_service import CategoryService
from subnet_validator.services.validator.playwright_coupon_validator import (
    PlaywrightCouponValidator,
)
from subnet_validator.services.validator.tlsn_coupon_validator import (
    TlsnCouponValidator,
)
from subnet_validator.services.validator.base import BaseCouponValidator
from subnet_validator.services.validator_sync_offset_service import (
    ValidatorSyncOffsetService,
)

from .services.coupon_service import (
    CouponService,
)

from .services.weight_calculator_service import (
    WeightCalculatorService,
)

from .services.metagraph_service import (
    MetagraphService,
)


from .services.dynamic_config_service import (
    DynamicConfigService,
)

from .services.site_service import (
    SiteService,
)

from .database.database import (
    get_db,
)
from .settings import (
    Settings,
)
from sqlalchemy.orm import (
    Session,
)


@lru_cache
def get_settings():
    return Settings()


def get_metagraph_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return MetagraphService(db)


def get_factory_config():
    """Get factory config with metagraph and substrate."""
    # Ensure metagraph is patched before creating factory config
    try:
        from subnet_validator.fiber_ext.metagraph import ExtendedMetagraph
        import fiber.chain.metagraph as mg

        # Only patch if not already patched
        if mg.Metagraph != ExtendedMetagraph:
            mg.Metagraph = ExtendedMetagraph  # type: ignore[attr-defined]
    except Exception as e:
        # If patching fails, continue with original metagraph
        pass

    from fiber.miner.core import configuration

    return configuration.factory_config()


def get_dynamic_config_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return DynamicConfigService(db)


def get_category_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return CategoryService(db)


def get_site_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return SiteService(db)


def get_coupon_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
    dynamic_config_service: Annotated[
        DynamicConfigService,
        Depends(get_dynamic_config_service),
    ],
    site_service: Annotated[
        SiteService,
        Depends(get_site_service),
    ],
):
    # Get metagraph from factory config
    factory_config = get_factory_config()
    metagraph = factory_config.metagraph

    return CouponService(
        db,
        dynamic_config_service,
        site_service,
        get_settings,
        metagraph=metagraph,
    )


def get_validator_sync_offset_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return ValidatorSyncOffsetService(db)


def get_weight_calculator_service(
    db: Annotated[
        Session,
        Depends(get_db),
    ],
):
    return WeightCalculatorService(
        db=db,
        get_settings=get_settings,
    )


def get_coupon_validator(
    site: Site,
    settings: Annotated[Settings, Depends(get_settings)],
    coupon_service: Annotated[CouponService, Depends(get_coupon_service)],
    metagraph_service: Annotated[
        MetagraphService, Depends(get_metagraph_service)
    ],
) -> BaseCouponValidator:
    try:
        if (
            site.config
            and isinstance(site.config, dict)
            and site.config.get("type") == "playwright"
        ):
            # Pass settings, metagraph and coupon_service for miner flow and ownership handling
            return TlsnCouponValidator(
                site=site,
                verifier_url=settings.tlsn_verifier_url,
                settings=settings,
                metagraph=metagraph_service,
                coupon_service=coupon_service,
            )
        if site.api_url:
            return ApiCouponValidator(
                site=site, storefront_password=settings.storefront_password
            )
        if site.config:
            return PlaywrightCouponValidator(site=site)
        raise ValueError("Site has no api_url or config")
    except Exception:
        # Fallback to API validator if misconfigured
        if site.api_url:
            return ApiCouponValidator(
                site=site, storefront_password=settings.storefront_password
            )
        if site.config:
            return PlaywrightCouponValidator(site=site)
        raise
