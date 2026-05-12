#!/usr/bin/env python3
"""
Test script: fetch bet events for an EVM address using the same logic as the validator.
Usage:
    python3 test_bet_fetch.py <EVM_ADDRESS>
    python3 test_bet_fetch.py <EVM_ADDRESS> --coldkey <COLDKEY>  # also check wallet mapping
"""

import sys
import argparse
from datetime import datetime, timedelta

# Use the same constants as the validator
from taocolosseum.core.const import (
    TAO_COLOSSEUM_CONTRACT_ADDRESS,
    BITTENSOR_EVM_RPC,
    BITTENSOR_EVM_CHAIN_ID,
    BLOCKS_PER_DAY,
    TIME_DECAY_WEIGHTS,
    DB_PATH,
)

try:
    from web3 import Web3
except ImportError:
    print("ERROR: web3 not installed. Run: pip install web3")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Test bet fetching with same logic as validator")
    parser.add_argument("evm_address", help="EVM address to query (0x...)")
    parser.add_argument("--coldkey", help="Optional: check wallet mapping for this coldkey in DB")
    parser.add_argument("--rpc", default=BITTENSOR_EVM_RPC, help=f"RPC URL (default: {BITTENSOR_EVM_RPC})")
    parser.add_argument("--contract", default=TAO_COLOSSEUM_CONTRACT_ADDRESS,
                        help=f"Contract address (default: {TAO_COLOSSEUM_CONTRACT_ADDRESS})")
    args = parser.parse_args()

    evm_address = args.evm_address
    rpc_url = args.rpc
    contract_address = args.contract

    print("=" * 70)
    print("TAO Colosseum - Bet Fetch Test")
    print("=" * 70)
    print(f"EVM Address:      {evm_address}")
    print(f"RPC URL:          {rpc_url}")
    print(f"Contract Address: {contract_address}")
    print(f"DB_PATH:          {DB_PATH}")
    print(f"Expected ChainID: {BITTENSOR_EVM_CHAIN_ID}")
    print()

    # ---- Step 1: Check wallet mapping in DB (if coldkey provided) ----
    if args.coldkey:
        print(f"--- Step 1: Checking wallet_mappings DB for coldkey: {args.coldkey[:16]}... ---")
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT coldkey, evm_address, verified_at FROM wallet_mappings WHERE coldkey = ?",
                (args.coldkey,),
            )
            row = cursor.fetchone()
            if row:
                print(f"  Found: coldkey={row[0][:16]}... evm={row[1]} verified_at={row[2]}")
            else:
                print(f"  NOT FOUND in wallet_mappings for coldkey {args.coldkey[:16]}...")

            # Also check if this EVM is mapped to any coldkey
            cursor.execute(
                "SELECT coldkey, evm_address, verified_at FROM wallet_mappings WHERE evm_address = ?",
                (evm_address.lower(),),
            )
            row2 = cursor.fetchone()
            if row2:
                print(f"  EVM {evm_address[:12]}... is mapped to coldkey={row2[0][:16]}... verified_at={row2[2]}")
            else:
                print(f"  EVM {evm_address[:12]}... NOT found in wallet_mappings by EVM lookup")
            conn.close()
        except Exception as e:
            print(f"  DB check failed: {e}")
        print()
    else:
        print("--- Step 1: Skipped (no --coldkey provided) ---")
        print()

    # ---- Step 2: Connect to RPC ----
    print("--- Step 2: Connecting to RPC ---")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    connected = w3.is_connected()
    print(f"  Connected: {connected}")
    if not connected:
        print("ERROR: Cannot connect to RPC. Check URL and network.")
        sys.exit(1)

    actual_chain_id = w3.eth.chain_id
    print(f"  Chain ID:  {actual_chain_id} (expected: {BITTENSOR_EVM_CHAIN_ID})")
    if actual_chain_id != BITTENSOR_EVM_CHAIN_ID:
        print(f"  *** CHAIN ID MISMATCH! RPC is serving chain {actual_chain_id}, "
              f"but const.py expects {BITTENSOR_EVM_CHAIN_ID} ***")
        print(f"  This likely means the RPC URL points to the WRONG network.")
        print(f"  Contract at {contract_address} may not exist on chain {actual_chain_id}.")

    current_block = w3.eth.block_number
    print(f"  Current block: {current_block}")

    # Check if contract has code at this address
    code = w3.eth.get_code(Web3.to_checksum_address(contract_address))
    if code and len(code) > 2:
        print(f"  Contract code:  YES ({len(code)} bytes)")
    else:
        print(f"  Contract code:  NONE - contract does NOT exist at this address on chain {actual_chain_id}!")
    print()

    # ---- Step 3: Compute block range (same as validator) ----
    from_block = max(0, current_block - (BLOCKS_PER_DAY * 7))
    print(f"--- Step 3: Block range (last 7 days) ---")
    print(f"  from_block:     {from_block}")
    print(f"  to_block:       {current_block}")
    print(f"  BLOCKS_PER_DAY: {BLOCKS_PER_DAY}")
    print()

    # ---- Step 4: Check bet_events cache in DB ----
    print("--- Step 4: Checking bet_events cache in DB ---")
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        seven_days_ago = int((datetime.utcnow() - timedelta(days=7)).timestamp())
        cursor.execute(
            "SELECT COUNT(*), MIN(block_number), MAX(block_number) "
            "FROM bet_events WHERE evm_address = ? AND contract_address = ? AND timestamp >= ?",
            (evm_address.lower(), contract_address, seven_days_ago),
        )
        row = cursor.fetchone()
        cached_count = row[0] or 0
        cached_min_block = row[1]
        cached_max_block = row[2]
        print(f"  Cached events: {cached_count}")
        if cached_count > 0:
            print(f"  Cached block range: {cached_min_block} - {cached_max_block}")
        conn.close()
    except Exception as e:
        print(f"  Cache check failed: {e}")
        cached_count = 0
    print()

    # ---- Step 5: Call get_logs (same as validator) ----
    print("--- Step 5: Calling eth_getLogs (same as validator) ---")

    # New ABI event signature (Underdog-only, no referrer)
    new_sig = w3.keccak(text="BetPlaced(uint256,address,uint8,uint256,uint256)")
    # Old ABI event signature (had referrer address as 6th param)
    old_sig = w3.keccak(text="BetPlaced(uint256,address,uint8,uint256,uint256,address)")

    checksum_address = Web3.to_checksum_address(evm_address)
    address_topic = '0x' + checksum_address[2:].lower().zfill(64)

    print(f"  NEW event sig (no referrer): 0x{new_sig.hex()}")
    print(f"  OLD event sig (w/ referrer): 0x{old_sig.hex()}")
    print(f"  Address topic:               {address_topic}")
    print(f"  Contract:                    {contract_address}")
    print(f"  Range:                       {from_block} -> {current_block}")
    print()

    # 5a: Try NEW signature with bettor filter (what the validator does)
    print("  [5a] NEW sig + bettor filter (validator logic)...")
    logs = []
    try:
        logs = w3.eth.get_logs({
            'fromBlock': from_block,
            'toBlock': current_block,
            'address': contract_address,
            'topics': [
                '0x' + new_sig.hex(),
                None,
                address_topic,
            ],
        })
        print(f"       -> {len(logs)} log(s)")
    except Exception as e:
        print(f"       -> FAILED: {type(e).__name__}: {e}")

    # 5b: Try OLD signature with bettor filter
    print("  [5b] OLD sig + bettor filter...")
    logs_old_sig = []
    try:
        logs_old_sig = w3.eth.get_logs({
            'fromBlock': from_block,
            'toBlock': current_block,
            'address': contract_address,
            'topics': [
                '0x' + old_sig.hex(),
                None,
                address_topic,
            ],
        })
        print(f"       -> {len(logs_old_sig)} log(s)")
    except Exception as e:
        print(f"       -> FAILED: {type(e).__name__}: {e}")

    # 5c: Try NEW signature WITHOUT bettor filter (all bettors)
    print("  [5c] NEW sig, NO bettor filter (all bets on contract)...")
    logs_all_new = []
    try:
        logs_all_new = w3.eth.get_logs({
            'fromBlock': from_block,
            'toBlock': current_block,
            'address': contract_address,
            'topics': [
                '0x' + new_sig.hex(),
            ],
        })
        print(f"       -> {len(logs_all_new)} log(s)")
    except Exception as e:
        print(f"       -> FAILED: {type(e).__name__}: {e}")

    # 5d: Try OLD signature WITHOUT bettor filter (all bettors)
    print("  [5d] OLD sig, NO bettor filter (all bets on contract)...")
    logs_all_old = []
    try:
        logs_all_old = w3.eth.get_logs({
            'fromBlock': from_block,
            'toBlock': current_block,
            'address': contract_address,
            'topics': [
                '0x' + old_sig.hex(),
            ],
        })
        print(f"       -> {len(logs_all_old)} log(s)")
    except Exception as e:
        print(f"       -> FAILED: {type(e).__name__}: {e}")

    # 5e: Query ALL events from contract (no topic filter)
    print("  [5e] ALL events from contract (no topic filter, last 1000 blocks)...")
    logs_any = []
    try:
        recent_from = max(from_block, current_block - 1000)
        logs_any = w3.eth.get_logs({
            'fromBlock': recent_from,
            'toBlock': current_block,
            'address': contract_address,
        })
        print(f"       -> {len(logs_any)} event(s) in last 1000 blocks")
        if logs_any:
            # Show unique event topic0 values (event signatures present)
            unique_sigs = set()
            for l in logs_any:
                if l.get('topics'):
                    unique_sigs.add(l['topics'][0].hex())
            print(f"       Unique event signatures found: {len(unique_sigs)}")
            for sig in sorted(unique_sigs):
                count = sum(1 for l in logs_any if l.get('topics') and l['topics'][0].hex() == sig)
                marker = ""
                if sig == new_sig.hex():
                    marker = " <-- NEW BetPlaced"
                elif sig == old_sig.hex():
                    marker = " <-- OLD BetPlaced (with referrer!)"
                print(f"         0x{sig}: {count} event(s){marker}")
    except Exception as e:
        print(f"       -> FAILED: {type(e).__name__}: {e}")

    print()

    # ---- Diagnosis ----
    print("--- Diagnosis ---")
    if len(logs) > 0:
        print("  OK: NEW event signature matched. Validator logic should work.")
        use_logs = logs
    elif len(logs_old_sig) > 0:
        print("  ** PROBLEM FOUND: OLD event signature matches but NEW does not! **")
        print("     The deployed contract still emits BetPlaced WITH referrer param.")
        print("     FIX: Update the validator ABI to use the OLD event signature,")
        print("     OR redeploy the contract with the new code.")
        use_logs = logs_old_sig
    elif len(logs_all_new) > 0:
        print("  ** Bettor topic filter issue: NEW sig found events for OTHER bettors but not this one.")
        print(f"     Address {evm_address} has 0 bets, but contract has {len(logs_all_new)} total bets (new sig).")
        use_logs = []
    elif len(logs_all_old) > 0:
        print("  ** PROBLEM: OLD event sig found events (not for this bettor).")
        print("     Contract uses OLD ABI + this address has 0 bets.")
        use_logs = []
    elif len(logs_any) > 0:
        print("  ** Contract is active (has events) but NO BetPlaced events found with either signature.")
        print("     Check if the event definition changed further.")
        use_logs = []
    else:
        print("  ** Contract appears INACTIVE: no events at all in last 1000 blocks.")
        print("     Possible: wrong contract address, wrong chain, or contract not yet used.")
        use_logs = []
    print()

    # ---- Step 6: Decode events and compute volume (same as validator) ----
    if use_logs:
        print(f"--- Step 6: Decoding {len(use_logs)} event(s) ---")
        daily_volumes = [0.0] * 7
        now = datetime.utcnow()

        for i, log in enumerate(use_logs[:20]):  # cap at 20 for display
            try:
                block_num = log['blockNumber']
                data = log['data']
                if isinstance(data, str):
                    data = bytes.fromhex(data[2:])
                # side = first 32 bytes, amount = next 32 bytes
                amount_wei = int.from_bytes(data[32:64], 'big')
                amount_tao = amount_wei / 1e18

                try:
                    block_info = w3.eth.get_block(block_num)
                    ts = block_info['timestamp']
                except Exception:
                    ts = int(now.timestamp())

                event_time = datetime.utcfromtimestamp(ts)
                days_ago = (now - event_time).days

                print(f"  [{i}] block={block_num} amount={amount_tao:.4f} TAO "
                      f"ts={ts} ({event_time.isoformat()}) days_ago={days_ago}")

                if 0 <= days_ago < 7:
                    daily_volumes[days_ago] += amount_tao
            except Exception as e:
                print(f"  [{i}] decode error: {e}")

        if len(use_logs) > 20:
            print(f"  ... and {len(use_logs) - 20} more events (not shown)")

        weighted_volume = sum(v * w for v, w in zip(daily_volumes, TIME_DECAY_WEIGHTS))

        print()
        print("--- Volume Summary ---")
        for day_idx, (vol, weight) in enumerate(zip(daily_volumes, TIME_DECAY_WEIGHTS)):
            label = "today" if day_idx == 0 else f"{day_idx}d ago"
            print(f"  {label:8s}: {vol:10.4f} TAO x {weight:.2f} = {vol * weight:10.4f}")
        print(f"  {'TOTAL':8s}: {sum(daily_volumes):10.4f} TAO raw, {weighted_volume:10.4f} TAO weighted")
    else:
        weighted_volume = 0.0
        print("--- Step 6: No usable events ---")

    print()
    print("=" * 70)
    print(f"RESULT: weighted_volume = {weighted_volume:.6f} TAO")
    if weighted_volume > 0:
        print("STATUS: Volume found - validator SHOULD assign non-zero weight")
    else:
        print("STATUS: Zero volume - validator WILL run burn code for this miner")
    print("=" * 70)


if __name__ == "__main__":
    main()
