import os
import json
import pytest
import requests
from dotenv import load_dotenv
load_dotenv()
from utils.taostats import get_alpha_price_from_taostats, get_tao_price_from_taostats


def test_get_tao_price_from_taostats():
    api_key = os.getenv("TAOSTATS_API_KEY")
    url = f"https://api.taostats.io/api/price/latest/v1?asset=tao"
    headers = {"accept": "application/json", "Authorization": api_key}
    response = requests.get(url, headers=headers)
    response.raise_for_status()    
    resJson = json.loads(response.text)    

    assert "data" in resJson
    price_data = resJson["data"][0]
    created_at = price_data.get("created_at")
    updated_at = price_data.get("updated_at")
    name = price_data.get("name")
    symbol = price_data.get("symbol")
    slug = price_data.get("slug")
    circulating_supply = price_data.get("circulating_supply")
    total_supply = price_data.get("total_supply")
    market_cap = price_data.get("market_cap")
    fully_diluted_market_cap = price_data.get("fully_diluted_market_cap")

    print(f"Created At: {created_at}")
    print(f"Updated At: {updated_at}")
    print(f"Name: {name}")
    print(f"Symbol: {symbol}")
    print(f"Slug: {slug}")
    print(f"Circulating Supply: {circulating_supply}")
    print(f"Total Supply: {total_supply}")
    print(f"Market Cap: {market_cap}")
    print(f"Fully Diluted Market Cap: {fully_diluted_market_cap}")

    assert created_at is not None
    assert updated_at is not None
    assert name == "Bittensor"
    assert symbol == "TAO"
    assert slug == "bittensor"
    assert circulating_supply is not None
    assert total_supply is not None
    assert market_cap is not None
    assert fully_diluted_market_cap is not None


def test_get_bitrecs_price_from_taostats():
    netuid = 122
    api_key = os.getenv("TAOSTATS_API_KEY")
    headers = {"accept": "application/json", "Authorization": api_key}    
    url = f"https://api.taostats.io/api/dtao/pool/latest/v1?netuid={netuid}&page=1"
    response = requests.get(url, headers=headers)
    resJson = json.loads(response.text)
    api_total_alpha = float(resJson['data'][0]['total_alpha'])/1e9
    alpha_in_pool = float(resJson['data'][0]['alpha_in_pool'])/1e9
    api_alpha_staked = float(resJson['data'][0]['alpha_staked'])/1e9
    alpha_price =float(resJson['data'][0]['price'])
    print(alpha_in_pool)
    print(api_total_alpha)
    print(api_alpha_staked)
    print(alpha_price)

    tao_price = get_tao_price_from_taostats()
    print(tao_price)
    bitrecs_price = alpha_price * tao_price
    print(bitrecs_price)
    assert bitrecs_price > 0
  

def get_value_from_alpha(alpha_burned_rao: int) -> float:
    tao_price = get_tao_price_from_taostats()
    alpha_price = get_alpha_price_from_taostats()
    alpha_burned = alpha_burned_rao / 1e9
    bitrecs_price = alpha_price * tao_price
    value = alpha_burned * bitrecs_price
    return value
    
@pytest.mark.skip(reason="skipped")
def test_one():
    tolerance = 3.0
    burned = 22823068312
    value = get_value_from_alpha(burned)
    print(f"Value for {burned} rao burned: {value} USD")
    assert value == pytest.approx(22.0, abs=tolerance)