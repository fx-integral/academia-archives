import bittensor as bt
from typing import Optional

class PingSynapse(bt.Synapse):
    """
    Unified Synapse for Ping operations between Validator and Miner.
    The validator sends a hotkey, and the miner responds with a token.
    """
    hotkey: str                     # Sent by Validator
    token: Optional[str] = None     # Set by Miner

    def forward(self) -> "PingSynapse":
        return self
