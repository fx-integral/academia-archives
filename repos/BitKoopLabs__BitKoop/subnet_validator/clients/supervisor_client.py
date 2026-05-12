import httpx
from typing import (
    Generic,
    List,
    Optional,
    TypeVar,
)
from pydantic import (
    BaseModel,
    Field,
)

SUPERVISOR_BASE_URL = "http://91.99.203.36/api"


T = TypeVar("T", bound=BaseModel)


class PagedResponse(BaseModel, Generic[T]):
    page: int
    limit: int
    total: int
    has_next_page: bool = Field(alias="hasNextPage")
    data: List[T]


class Site(BaseModel):
    store_id: int
    store_domain: str
    store_status: int  # 0 = inactive, 1 = active, 2 = pending
    miner_hotkey: str | None = None
    api_url: str | None = None
    config: dict | None = None
    total_coupon_slots: int = 15  # Default to 15 slots


class ProductCategory(BaseModel):
    category_id: int
    category_name: str


class SupervisorApiClient:
    """
    Async API client for the Supervisor service.
    Provides methods to fetch sites and product categories.
    """

    def __init__(
        self,
        base_url: str = SUPERVISOR_BASE_URL,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(
        self,
    ):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        if self._client:
            await self._client.aclose()

    async def get_sites(
        self,
        page: int = 1,
        page_size: int = 100,
    ) -> List[Site]:
        """
        Fetches the list of sites with their statuses.
        Returns a list of Site objects.
        """
        params = {
            "page": page,
            "limit": page_size,
        }
        url = f"{self.base_url}/sites"
        async with self._client as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return PagedResponse[Site].model_validate(resp.json()).data

    async def get_product_categories(
        self,
        page: int = 1,
        page_size: int = 100,
    ) -> List[ProductCategory]:
        """
        Fetches the list of product categories.
        Returns a list of ProductCategory objects.
        """
        url = f"{self.base_url}/product-categories"
        params = {
            "page": page,
            "limit": page_size,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return PagedResponse[ProductCategory].model_validate(data).data
