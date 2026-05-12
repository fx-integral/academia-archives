import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()
from cachetools import cached, TTLCache


@cached(cache=TTLCache(maxsize=1, ttl=900))
def get_tao_price_from_taostats() -> float:
    api_key = os.getenv("TAOSTATS_API_KEY")
    url = f"https://api.taostats.io/api/price/latest/v1?asset=tao"
    headers = {"accept": "application/json", "Authorization": api_key}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    resJson = json.loads(response.text)
    price_data = resJson["data"][0]
    price = price_data.get("price")
    float_price = float(price)
    return float_price


@cached(cache=TTLCache(maxsize=1, ttl=900))
def get_alpha_price_from_taostats() -> float:
    netuid = 122
    api_key = os.getenv("TAOSTATS_API_KEY")
    headers = {"accept": "application/json", "Authorization": api_key}    
    url = f"https://api.taostats.io/api/dtao/pool/latest/v1?netuid={netuid}&page=1"
    response = requests.get(url, headers=headers)
    resJson = json.loads(response.text)   
    alpha_price = float(resJson['data'][0]['price'])
    return alpha_price


# def get_value_from_alpha(alpha_burned_rao: float) -> float:
#     """
#     Takes raw rao amount and returns the value in USD based on the current price of alpha and tao.
#     """
#     tao_price = get_tao_price_from_taostats()
#     alpha_price = get_alpha_price_from_taostats()
#     alpha_burned = alpha_burned_rao / 1e9
#     bitrecs_price = alpha_price * tao_price
#     value = alpha_burned * bitrecs_price
#     return value