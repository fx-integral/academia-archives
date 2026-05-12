import aiohttp

from neurons.validator.models.unusual_whales import NewsHeadline, NewsHeadlinesResponse

DEFAULT_BASE_URL = "https://api.unusualwhales.com"
DEFAULT_TIMEOUT = 45.0


class UnusualWhalesClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise ValueError("Unusual Whales API key is not set")
        self.__api_key = api_key
        self.__base_url = base_url
        self.__timeout = aiohttp.ClientTimeout(total=timeout)
        self.__headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.__api_key}",
        }

    async def get_news_headlines(
        self,
        sources: str | None = None,
        search_term: str | None = None,
        ticker: str | None = None,
        major_only: bool | None = None,
        limit: int = 50,
        page: int = 0,
    ) -> NewsHeadlinesResponse:
        url = f"{self.__base_url}/api/news/headlines"
        params: dict[str, str | int] = {"limit": limit, "page": page}
        if sources:
            params["sources"] = sources
        if search_term:
            params["search_term"] = search_term
        if ticker:
            params["ticker"] = ticker
        if major_only is not None:
            params["major_only"] = str(major_only).lower()

        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                headlines = [NewsHeadline.model_validate(item) for item in data.get("data", [])]
                return NewsHeadlinesResponse(headlines=headlines)
