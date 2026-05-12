from dataclasses import dataclass
from sqlalchemy.orm import Session
from fiber import SubstrateInterface
from typing import Optional, List
import httpx

from . import dependencies
from .services.weight_calculator_service import WeightCalculatorService
from .services.coupon_service import CouponService
from .services.site_service import SiteService
from .fiber_ext.node import ExtendedNode


@dataclass
class AppContext:
    """Centralized application context holding shared resources (no DB sessions)."""

    factory_config: object  # Factory config with metagraph and substrate
    http_client: Optional[httpx.AsyncClient] = None

    @property
    def substrate(self):
        """Get substrate from factory config."""
        return self.factory_config.substrate

    @property
    def metagraph(self):
        """Get metagraph from factory config."""
        return self.factory_config.metagraph

    def get_settings(self):
        """Get settings dynamically - can be extended to fetch from external sources."""
        # For now, use the standard get_settings() delegate
        # Later: can be extended to fetch from external API using self.http_client
        # Example future implementation:
        # if self.http_client:
        #     response = await self.http_client.get("https://api.example.com/settings")
        #     return Settings(**response.json())
        return dependencies.get_settings()

    def create_services(self, db: Session):
        """Create services with a specific DB session (thread-safe)."""
        # Create base services
        dynamic_config_service = dependencies.get_dynamic_config_service(db=db)
        site_service = SiteService(db=db)

        return {
            "weight_calculator": WeightCalculatorService(
                db=db, get_settings=self.get_settings
            ),
            "dynamic_config_service": dynamic_config_service,
            "coupon_service": CouponService(
                db=db,
                dynamic_config_service=dynamic_config_service,
                site_service=site_service,
                get_settings=self.get_settings,
                metagraph=self.metagraph,
            ),
            "site_service": site_service,
        }

    def close(self):
        """Clean up resources."""
        if self.http_client:
            # Close the HTTP client to free resources
            import asyncio

            try:
                # Try to close synchronously first
                if hasattr(self.http_client, "aclose"):
                    asyncio.create_task(self.http_client.aclose())
            except Exception:
                # If async close fails, we'll let the garbage collector handle it
                pass
