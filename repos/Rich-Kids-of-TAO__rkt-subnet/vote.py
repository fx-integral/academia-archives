#!/usr/bin/env python3

import json
import requests
import argparse
import bittensor as bt


def main():
    print("=== Miner Appreciation Voting CLI ===\n")

    parser = argparse.ArgumentParser(description="Vote for subnet weights")
    parser.add_argument(
        "--wallet.name",
        type=str,
        required=True,
        help="Name of wallet",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="https://richkidsoftao.com/api/vote",
        help="API endpoint URL",
    )
    args = parser.parse_args()

    # Load wallet config (don't access coldkey yet to avoid double password prompt)
    try:
        config = bt.config(parser)
        wallet = bt.wallet(config=config)
        print(f"Using wallet: {wallet.name}\n")
    except Exception as e:
        print(f"Error loading wallet: {e}")
        return

    # Get subnet weights from user FIRST
    print("Enter subnet weights as JSON (must sum to 1.0)")
    print('Example: {"10":0.2,"51":0.15,"64":0.15,"62":0.2,"4":0.1,"8":0.1,"13":0.1}')
    print("Or press Enter for default weights\n")

    weights_input = input("Subnet weights: ").strip()

    if not weights_input:
        # Default weights
        subnets = {
            "10": 0.2,
            "51": 0.15,
            "64": 0.15,
            "62": 0.2,
            "4": 0.1,
            "8": 0.1,
            "13": 0.1,
        }
        print("Using default weights")
    else:
        # Parse JSON input
        try:
            subnets = json.loads(weights_input)
            # Ensure keys are strings and values are floats
            subnets = {str(k): float(v) for k, v in subnets.items()}
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            print(
                'Please use JSON format like: {"10":0.2,"51":0.15,"64":0.15,"62":0.2,"4":0.1,"8":0.1,"13":0.1}'
            )
            return

    # Validate weights sum to 1.0
    total = sum(subnets.values())
    if abs(total - 1.0) > 0.001:
        print(f"Error: Weights must sum to 1.0 (got {total})")
        return

    print(f"\nSubmitting vote:")
    for netuid, weight in subnets.items():
        print(f"  Subnet {netuid}: {weight:.2%}")

    # Now access coldkey (will prompt for password once)
    print("\n")
    try:
        coldkey_keypair = wallet.coldkey
        coldkey_address = coldkey_keypair.ss58_address
        print(f"Using coldkey: {coldkey_address}")
    except Exception as e:
        print(f"Error accessing coldkey: {e}")
        return

    # Create message to sign (use compact JSON format to match JavaScript)
    # Sort subnet keys to ensure consistent ordering with JavaScript
    sorted_subnets = dict(sorted(subnets.items()))
    vote_data = {"coldkey": coldkey_address, "subnets": sorted_subnets}
    message = json.dumps(vote_data, separators=(",", ":"), sort_keys=True)

    # Sign the message (coldkey already decrypted)
    signature = coldkey_keypair.sign(message.encode())
    signature_hex = "0x" + signature.hex()

    print(f"Signature: {signature_hex[:20]}...{signature_hex[-20:]}\n")

    # Submit to API
    payload = {
        "coldkey": coldkey_address,
        "subnets": subnets,
        "signature": signature_hex,
        "message": message,
    }

    try:
        response = requests.post(args.api_url, json=payload, timeout=10)
        result = response.json()

        if response.status_code == 200 and result.get("success"):
            print("✓ Vote submitted successfully!")
            print(f"  Total voters: {result.get('totalVoters', 'N/A')}")
        else:
            print(f"✗ Vote failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"✗ Failed to submit vote: {e}")


if __name__ == "__main__":
    main()
