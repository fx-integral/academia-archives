import json

import pytest

from miner.pool.wallet_utils.btcli import parse_btcli_wallets


JSON_OUTPUT = json.dumps(
    {
        "coldkeys": [
            {
                "name": "iota",
                "ss58_address": "5EEmPQ8mEmVcu6UgZVG3uXL4wPg4M6wbESR7w2Nf8VNMHhPt",
                "hotkeys": [
                    {
                        "name": "iota_miner",
                        "ss58_address": "5HKz3xqBEevU2AhjUcjMYH9jpkJi2yLysc6WaTFV8TQiMyFU",
                    }
                ],
            }
        ]
    }
)


ALT_JSON_OUTPUT = json.dumps(
    {
        "wallets": [
            {
                "wallet_name": "iota",
                "address": "5EEmPQ8mEmVcu6UgZVG3uXL4wPg4M6wbESR7w2Nf8VNMHhPt",
                "coldkey_hotkeys": [
                    {
                        "hotkey_name": "iota_miner",
                        "address": "5HKz3xqBEevU2AhjUcjMYH9jpkJi2yLysc6WaTFV8TQiMyFU",
                    }
                ],
            }
        ]
    }
)


def _expected_wallet():
    return {
        "coldkeys": [
            {
                "name": "iota",
                "ss58_address": "5EEmPQ8mEmVcu6UgZVG3uXL4wPg4M6wbESR7w2Nf8VNMHhPt",
                "hotkeys": [
                    {
                        "name": "iota_miner",
                        "ss58_address": "5HKz3xqBEevU2AhjUcjMYH9jpkJi2yLysc6WaTFV8TQiMyFU",
                    }
                ],
            }
        ]
    }


def test_parse_btcli_wallets_json_output():
    result = parse_btcli_wallets(JSON_OUTPUT)
    assert result == _expected_wallet()


def test_parse_btcli_wallets_handles_alternate_keys():
    result = parse_btcli_wallets(ALT_JSON_OUTPUT)
    assert result == _expected_wallet()


def test_parse_btcli_wallets_invalid_json():
    with pytest.raises(ValueError):
        parse_btcli_wallets("not json")
