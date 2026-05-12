import typing

import aiohttp

from neurons.validator.models.lightning_rod import LightningRodCompletion


class LightningRodClient:
    __api_key: str
    __base_url: str
    __timeout: aiohttp.ClientTimeout
    __headers: dict[str, str]

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Lightning Rod API key is not set")

        self.__api_key = api_key
        self.__base_url = "https://api.lightningrod.ai/api/public/v1/openai"
        self.__timeout = aiohttp.ClientTimeout(total=300)
        self.__headers = {
            "Authorization": f"Bearer {self.__api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, typing.Any]],
        temperature: float = 0.7,
        max_tokens: typing.Optional[int] = None,
        **kwargs: typing.Any,
    ) -> LightningRodCompletion:
        body: dict[str, typing.Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        body.update(kwargs)

        url = f"{self.__base_url}/chat/completions"

        async with aiohttp.ClientSession(timeout=self.__timeout, headers=self.__headers) as session:
            async with session.post(url, json=body) as response:
                response.raise_for_status()
                data = await response.json()
                return LightningRodCompletion.model_validate(data)
