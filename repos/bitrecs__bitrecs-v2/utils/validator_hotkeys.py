
WHITELISTED_VALIDATORS = [
    {"hotkey": "5E7ooDPMFb8FMrnVD7z3B6ebkaNZRA5ksi87azE5okJsn122", "name": "RT21", "short_name": "RT21", "env": "mainnet" },
    {"hotkey": "5FtG4tgLC6ypK4veNwRd9C2SJGfHzckzjV9JafWtPUWzRCYy", "name": "Taocom", "short_name": "Taocom", "env": "mainnet" },
    {"hotkey": "5CXEbmzg7SD9dAsxep8MpjE28PbHxPotE63UnzLqu9VB99Tr", "name": "Bitrecs", "short_name": "Bitrecs", "env": "mainnet" },
    {"hotkey": "5Dd76FfntpDjfYJK8Mwnq1yPTAw9QW7vHfxNQdiWxVgmkfk6", "name": "Yuma", "short_name": "Yuma", "env": "mainnet" },
    {"hotkey": "5CZoa8Uw2GjkHfg3vybiiG5iGGAqqbDR6BdvhqJbj2Avs122", "name": "Rizzo", "short_name": "Rizzo", "env": "mainnet" },  

    # Developer validators, used for testing    
    {"hotkey": "5FNL6e4JsB3ZPUGk1x1izK1xnTWsZDZrVF6WaRp1gNpoTvsM", "name": "DimiTestValidator1", "short_name": "Dimi1", "env": "testnet" },  
    {"hotkey": "5FtH6Aj3xKbkNdgbZUghkTeJrkJexn6eBRZSnS8Zgc3oo4GX", "name": "DimiTestValidator2", "short_name": "Dimi2", "env": "testnet" },
    {"hotkey": "5Eyj7B2PzUMzRpW59eXziw4LazsQkn8bESF5gnbchyTdZEhX", "name": "MaxTestValidator1", "short_name": "Max1", "env": "testnet" }

]

TEST_VALIDATOR_HOTKEYS = [validator["hotkey"] for validator in WHITELISTED_VALIDATORS if validator["env"] == "testnet"]

MAINNET_VALIDATOR_HOTKEYS = [validator["hotkey"] for validator in WHITELISTED_VALIDATORS if validator["env"] == "mainnet"]

def is_validator_hotkey_whitelisted(validator_hotkey: str) -> bool:
    return validator_hotkey in [validator["hotkey"] for validator in WHITELISTED_VALIDATORS]

def validator_name_to_hotkey(validator_name: str) -> str:
    return next((validator["hotkey"] for validator in WHITELISTED_VALIDATORS if validator["name"] == validator_name), 'unknown')

def validator_hotkey_to_name(validator_hotkey: str) -> str:
    return next((validator["name"] for validator in WHITELISTED_VALIDATORS if validator["hotkey"] == validator_hotkey), 'unknown')