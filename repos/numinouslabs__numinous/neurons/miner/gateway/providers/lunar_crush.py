import aiohttp

from neurons.validator.models.lunar_crush import (
    LunarCrushCoinsListResponse,
    LunarCrushNewsResponse,
    LunarCrushPostsResponse,
    LunarCrushTimeSeriesResponse,
    LunarCrushTopicResponse,
    LunarCrushWhatsupResponse,
)


class LunarCrushClient:
    __api_key: str
    __base_url: str
    __timeout: aiohttp.ClientTimeout
    __headers: dict[str, str]

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("LunarCrush API key is not set")

        self.__api_key = api_key
        self.__base_url = "https://lunarcrush.com/api4/public"
        self.__timeout = aiohttp.ClientTimeout(total=30)
        self.__headers = {
            "Authorization": f"Bearer {self.__api_key}",
        }

    async def get_topic(self, topic: str) -> LunarCrushTopicResponse:
        url = f"{self.__base_url}/topic/{topic}/v1"
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushTopicResponse.model_validate(data)

    async def get_topic_time_series(
        self, topic: str, bucket: str = "day"
    ) -> LunarCrushTimeSeriesResponse:
        url = f"{self.__base_url}/topic/{topic}/time-series/v2"
        params = {"bucket": bucket}
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushTimeSeriesResponse.model_validate(data)

    async def get_topic_news(self, topic: str) -> LunarCrushNewsResponse:
        url = f"{self.__base_url}/topic/{topic}/news/v1"
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushNewsResponse.model_validate(data)

    async def get_topic_whatsup(self, topic: str) -> LunarCrushWhatsupResponse:
        url = f"{self.__base_url}/topic/{topic}/whatsup/v1"
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushWhatsupResponse.model_validate(data)

    async def get_topic_posts(
        self, topic: str, start: int | None = None, end: int | None = None
    ) -> LunarCrushPostsResponse:
        url = f"{self.__base_url}/topic/{topic}/posts/v1"
        params = {}
        if start is not None:
            params["start"] = str(start)
        if end is not None:
            params["end"] = str(end)
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url, params=params or None) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushPostsResponse.model_validate(data)

    async def get_coins_list(self) -> LunarCrushCoinsListResponse:
        url = f"{self.__base_url}/coins/list/v2"
        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return LunarCrushCoinsListResponse.model_validate(data)
