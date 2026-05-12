# The MIT License (MIT)
# Copyright © 2026 TAO Colosseum

"""
Contract interaction module for TAO Colosseum validator.
Queries the TAO Colosseum smart contract on Bittensor EVM.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import bittensor as bt

try:
    from web3 import Web3
    from web3.exceptions import ContractLogicError
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    bt.logging.warning("web3 not installed. Install with: pip install web3")

from taocolosseum.core.const import (
    TAO_COLOSSEUM_CONTRACT_ADDRESS,
    BITTENSOR_EVM_RPC,
    BITTENSOR_EVM_CHAIN_ID,
    BLOCKS_PER_DAY,
    TIME_DECAY_WEIGHTS,
)
from taocolosseum.validator.database import cache_bet_event, get_cached_bet_events


def _is_rate_limit_error(e: Exception) -> bool:
    """Heuristic: exception message/str suggests RPC rate limit or throttling."""
    s = (str(e) or "").lower()
    return any(
        x in s
        for x in (
            "429",
            "rate limit",
            "rate_limit",
            "too many request",
            "throttl",
            "quota exceeded",
            "limit exceeded",
        )
    )


# TAO Colosseum contract ABI - only the functions/events we need
# Matches TAO_Colosseum.sol: Underdog only, no referral, BetPlaced without referrer, UserStats without referralEarnings
colosseum_ABI = [
    # getUserStats function
    {
        "inputs": [{"name": "_user", "type": "address"}],
        "name": "getUserStats",
        "outputs": [
            {"name": "totalBets", "type": "uint256"},
            {"name": "totalWins", "type": "uint256"},
            {"name": "totalWinnings", "type": "uint256"},
            {"name": "totalLosses", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    # BetPlaced event (gameId, bettor, side, amount, newPoolTotal - no referrer)
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "gameId", "type": "uint256"},
            {"indexed": True, "name": "bettor", "type": "address"},
            {"indexed": False, "name": "side", "type": "uint8"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "newPoolTotal", "type": "uint256"}
        ],
        "name": "BetPlaced",
        "type": "event"
    },
    # GameResolved event - only games with a winner; tied/cancelled games do not emit this
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "gameId", "type": "uint256"},
            {"indexed": False, "name": "winningSide", "type": "uint8"},
            {"indexed": False, "name": "redPool", "type": "uint256"},
            {"indexed": False, "name": "bluePool", "type": "uint256"},
            {"indexed": False, "name": "redBettors", "type": "uint256"},
            {"indexed": False, "name": "blueBettors", "type": "uint256"}
        ],
        "name": "GameResolved",
        "type": "event"
    }
]


class ContractClient:
    """Client for interacting with the TAO Colosseum contract."""
    
    def __init__(self, rpc_url: str = None, contract_address: str = None):
        if not WEB3_AVAILABLE:
            raise ImportError("web3 is required. Install with: pip install web3")
        
        self.rpc_url = rpc_url or BITTENSOR_EVM_RPC
        self.contract_address = contract_address or TAO_COLOSSEUM_CONTRACT_ADDRESS
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.contract_address),
            abi=colosseum_ABI
        )
        # Cache for resolved game IDs (same block range reused across miners in one volume check)
        self._resolved_cache: Optional[tuple] = None  # (from_block, to_block, set) or None
        
        bt.logging.info(
            f"ContractClient initialized: contract={self.contract_address}, rpc={self.rpc_url}"
        )
        
        # Verify chain ID matches expected network
        try:
            actual_chain_id = self.w3.eth.chain_id
            if actual_chain_id != BITTENSOR_EVM_CHAIN_ID:
                bt.logging.warning(
                    f"CHAIN ID MISMATCH: RPC returned chain_id={actual_chain_id}, "
                    f"expected {BITTENSOR_EVM_CHAIN_ID}. Wrong network!"
                )
            else:
                bt.logging.info(f"Chain ID verified: {actual_chain_id}")
        except Exception as e:
            bt.logging.warning(f"Could not verify chain ID: {e}")
        
        # Verify contract exists at address
        try:
            code = self.w3.eth.get_code(Web3.to_checksum_address(self.contract_address))
            if not code or len(code) <= 2:
                bt.logging.warning(
                    f"NO CONTRACT CODE at {self.contract_address} on chain {BITTENSOR_EVM_CHAIN_ID}! "
                    f"Contract may not be deployed or wrong address."
                )
            else:
                bt.logging.info(f"Contract verified: {len(code)} bytes of code at {self.contract_address[:12]}...")
        except Exception as e:
            bt.logging.warning(f"Could not verify contract code: {e}")
    
    def is_connected(self) -> bool:
        """Check if connected to the RPC."""
        try:
            return self.w3.is_connected()
        except Exception:
            return False
    
    def get_current_block(self) -> int:
        """Get the current block number."""
        return self.w3.eth.block_number
    
    def get_user_stats(self, address: str) -> Optional[Dict]:
        """
        Get user stats from the contract.
        
        Args:
            address: EVM address to query
            
        Returns:
            Dict with totalBets, totalWins, totalWinnings, totalLosses
        """
        try:
            checksum_address = Web3.to_checksum_address(address)
            stats = self.contract.functions.getUserStats(checksum_address).call()
            
            return {
                'total_bets': stats[0],
                'total_wins': stats[1],
                'total_winnings': stats[2],  # In wei
                'total_losses': stats[3]
            }
        except ContractLogicError as e:
            bt.logging.debug(f"Contract error for {address}: {e}")
            return None
        except Exception as e:
            bt.logging.warning(f"Error getting user stats for {address}: {e}")
            return None
    
    def get_bet_events(
        self, 
        address: str, 
        from_block: int, 
        to_block: int = None
    ) -> List[Dict]:
        """
        Get BetPlaced events for an address within a block range.
        
        Args:
            address: EVM address to query
            from_block: Starting block
            to_block: Ending block (default: latest)
            
        Returns:
            List of bet event dicts
        """
        try:
            checksum_address = Web3.to_checksum_address(address)
            to_block_val = to_block if to_block else self.w3.eth.block_number
            
            # Get the event topic (BetPlaced event signature hash)
            # BetPlaced(uint256 indexed gameId, address indexed bettor, uint8 side, uint256 amount, uint256 newPoolTotal)
            event_signature = self.w3.keccak(text="BetPlaced(uint256,address,uint8,uint256,uint256)")
            
            # Pad the address to 32 bytes for indexed parameter filtering
            address_topic = '0x' + checksum_address[2:].lower().zfill(64)
            
            # Use eth.get_logs directly - most reliable approach
            bt.logging.info(
                f"get_logs: address={address[:10]}...0x{address[-6:]} "
                f"from_block={from_block} to_block={to_block_val} contract={self.contract_address[:10]}..."
            )
            logs = self.w3.eth.get_logs({
                'fromBlock': from_block,
                'toBlock': to_block_val,
                'address': self.contract_address,
                'topics': [
                    '0x' + event_signature.hex(),  # Event signature (0x-prefixed)
                    None,                   # gameId (indexed, but we want all)
                    address_topic           # bettor (indexed)
                ]
            })
            bt.logging.info(
                f"get_logs returned {len(logs)} log(s) for {address[:10]}...0x{address[-6:]}"
            )
            
            bet_events = []
            for log in logs:
                try:
                    # Decode the event data
                    decoded = self.contract.events.BetPlaced().process_log(log)
                    
                    # Get block timestamp
                    try:
                        block = self.w3.eth.get_block(log['blockNumber'])
                        timestamp = block['timestamp']
                    except Exception:
                        timestamp = int(datetime.utcnow().timestamp())
                    
                    bet_event = {
                        'game_id': decoded['args']['gameId'],
                        'bettor': decoded['args']['bettor'],
                        'side': decoded['args']['side'],
                        'amount': decoded['args']['amount'],  # In wei
                        'block_number': log['blockNumber'],
                        'timestamp': timestamp,
                        'tx_hash': log['transactionHash'].hex()
                    }
                    bet_events.append(bet_event)
                    
                    # Cache the event with contract address
                    cache_bet_event(
                        evm_address=address.lower(),
                        game_id=bet_event['game_id'],
                        amount=float(self.w3.from_wei(bet_event['amount'], 'ether')),
                        side=bet_event['side'],
                        block_number=bet_event['block_number'],
                        timestamp=bet_event['timestamp'],
                        contract_address=self.contract_address
                    )
                except Exception as decode_err:
                    bt.logging.debug(f"Error decoding log: {decode_err}")
                    continue
            
            return bet_events
            
        except Exception as e:
            bt.logging.warning(
                f"get_logs failed for {address[:10]}... from_block={from_block} "
                f"to_block={to_block or 'latest'}: {type(e).__name__}: {e}"
            )
            if _is_rate_limit_error(e):
                bt.logging.warning(
                    "RPC rate limit or throttling suspected (429/rate limit in error). "
                    "Consider using a dedicated RPC or increasing request spacing."
                )
            return []
    
    def get_resolved_game_ids(self, from_block: int, to_block: int = None) -> set:
        """
        Get set of game IDs that were resolved with a winner in the block range.
        Tied/cancelled games do not emit GameResolved, so their bets must be excluded from volume.
        
        Args:
            from_block: Starting block
            to_block: Ending block (default: latest)
            
        Returns:
            Set of game_id (int) that have a winner
        """
        try:
            to_block_val = to_block if to_block is not None else self.w3.eth.block_number
            if self._resolved_cache is not None:
                c_from, c_to, c_set = self._resolved_cache
                if c_from == from_block and c_to == to_block_val:
                    return c_set
            resolved = set()
            event_signature = self.w3.keccak(
                text="GameResolved(uint256,uint8,uint256,uint256,uint256,uint256)"
            )
            logs = self.w3.eth.get_logs({
                'fromBlock': from_block,
                'toBlock': to_block_val,
                'address': self.contract_address,
                'topics': ['0x' + event_signature.hex()]
            })
            for log in logs:
                try:
                    decoded = self.contract.events.GameResolved().process_log(log)
                    resolved.add(decoded['args']['gameId'])
                except Exception as decode_err:
                    bt.logging.debug(f"Error decoding GameResolved log: {decode_err}")
                    continue
            if resolved:
                bt.logging.debug(
                    f"get_resolved_game_ids: {from_block}..{to_block_val} -> {len(resolved)} resolved game(s)"
                )
            self._resolved_cache = (from_block, to_block_val, resolved)
            return resolved
        except Exception as e:
            bt.logging.warning(
                f"get_resolved_game_ids failed from_block={from_block} to_block={to_block}: {e}"
            )
            if _is_rate_limit_error(e):
                bt.logging.warning(
                    "RPC rate limit suspected (GameResolved fetch). Consider dedicated RPC."
                )
            return set()
    
    def get_bets_last_7_days(self, address: str) -> List[Dict]:
        """
        Get bets from the last 7 days for an address that belong to resolved games only.
        Tied/cancelled games are excluded so volume cannot be gamed by refunded bets.
        
        Args:
            address: EVM address to query
            
        Returns:
            List of bet event dicts (only from games that emitted GameResolved)
        """
        try:
            current_block = self.get_current_block()
            from_block = max(0, current_block - (BLOCKS_PER_DAY * 7))
            bt.logging.info(
                f"get_bets_last_7_days: {address[:10]}...0x{address[-6:]} "
                f"from_block={from_block} current_block={current_block}"
            )
            
            # First check cache (only for current contract)
            seven_days_ago = int((datetime.utcnow() - timedelta(days=7)).timestamp())
            cached_events = get_cached_bet_events(
                address.lower(), 
                seven_days_ago,
                contract_address=self.contract_address
            )
            
            new_events = []
            if cached_events:
                last_cached_block = max(e['block_number'] for e in cached_events)
                if last_cached_block < current_block - 100:
                    from_block = last_cached_block + 1
                    new_events = self.get_bet_events(address, from_block)
                else:
                    bt.logging.debug(f"Using cached events only for {address[:10]}...")
            else:
                new_events = self.get_bet_events(address, from_block)
            
            # Combine cached and new events (or cached only if cache is fresh)
            all_events = cached_events + [
                {
                    'game_id': e['game_id'],
                    'amount': float(self.w3.from_wei(e['amount'], 'ether')),
                    'side': e['side'],
                    'block_number': e['block_number'],
                    'timestamp': e['timestamp']
                }
                for e in new_events
            ]
            
            # Only count volume from games that were resolved with a winner (exclude tied/cancelled)
            from_block = max(0, current_block - (BLOCKS_PER_DAY * 7))
            resolved_game_ids = self.get_resolved_game_ids(from_block, current_block)
            filtered_events = [e for e in all_events if e['game_id'] in resolved_game_ids]
            excluded = len(all_events) - len(filtered_events)
            if excluded > 0:
                bt.logging.debug(
                    f"get_bets_last_7_days: excluded {excluded} bet(s) from tied/cancelled games "
                    f"({len(filtered_events)} from resolved games)"
                )
            
            if len(filtered_events) == 0:
                bt.logging.info(
                    f"get_bets_last_7_days: {address[:10]}... returned 0 events "
                    f"(no bets in range, or RPC returned none, or all from tied/cancelled games)"
                )
            else:
                bt.logging.info(
                    f"get_bets_last_7_days: {address[:10]}... returned {len(filtered_events)} event(s) "
                    f"(cached={len(cached_events)}, from_chain={len(new_events)}, "
                    f"resolved_only; raw total was {len(all_events)})"
                )
            return filtered_events
            
        except Exception as e:
            bt.logging.warning(
                f"get_bets_last_7_days failed for {address[:10]}...: {type(e).__name__}: {e}"
            )
            if _is_rate_limit_error(e):
                bt.logging.warning(
                    "RPC rate limit or throttling suspected (429/rate limit in error). "
                    "Consider using a dedicated RPC or increasing request spacing."
                )
            return []


def calculate_time_decayed_volume(bet_events: List[Dict]) -> tuple:
    """
    Calculate time-decayed volume from bet events.
    
    Args:
        bet_events: List of bet events with 'timestamp' and 'amount'
        
    Returns:
        Tuple of (weighted_volume, daily_volumes_list)
    """
    now = datetime.utcnow()
    daily_volumes = [0.0] * 7  # [today, yesterday, ..., 6 days ago]
    
    for event in bet_events:
        try:
            event_time = datetime.utcfromtimestamp(event['timestamp'])
            days_ago = (now - event_time).days
            
            if 0 <= days_ago < 7:
                # Amount should already be in TAO (ether units)
                amount = event.get('amount', 0)
                if isinstance(amount, int):
                    # If still in wei, convert
                    amount = amount / 1e18
                daily_volumes[days_ago] += amount
        except Exception as e:
            bt.logging.debug(f"Error processing bet event: {e}")
            continue
    
    # Apply decay weights
    weighted_volume = sum(
        vol * weight 
        for vol, weight in zip(daily_volumes, TIME_DECAY_WEIGHTS)
    )
    
    return weighted_volume, daily_volumes


def get_miner_volume(client: ContractClient, evm_address: str) -> tuple:
    """
    Get time-decayed betting volume for a miner's EVM address.
    
    Args:
        client: ContractClient instance
        evm_address: Miner's EVM address
        
    Returns:
        Tuple of (weighted_volume, daily_volumes)
    """
    if not evm_address:
        return 0.0, [0.0] * 7
    
    try:
        bet_events = client.get_bets_last_7_days(evm_address)
        return calculate_time_decayed_volume(bet_events)
    except Exception as e:
        bt.logging.warning(f"Error getting miner volume for {evm_address[:10]}...: {type(e).__name__}: {e}")
        if _is_rate_limit_error(e):
            bt.logging.warning(
                "RPC rate limit or throttling suspected. Consider dedicated RPC or request spacing."
            )
        return 0.0, [0.0] * 7


# Singleton client instance
_contract_client: Optional[ContractClient] = None


def get_contract_client() -> ContractClient:
    """Get or create the singleton contract client."""
    global _contract_client
    if _contract_client is None:
        _contract_client = ContractClient()
    return _contract_client
