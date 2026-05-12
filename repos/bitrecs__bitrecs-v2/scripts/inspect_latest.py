
import bittensor
import sys

def run():
    if len(sys.argv) < 3:
        print("Usage: uv run python inspect_latest.py <BLOCK_HASH> <EXTRINSIC_INDEX>")
        # Default to a recent one if you want, or just exit
        return

    BLOCK_HASH = sys.argv[1]
    EXTRINSIC_IDX = int(sys.argv[2])

    try:
        print("Connecting to Testnet...")
        sub = bittensor.Subtensor(network='test')
        substrate = sub.substrate
        
        print(f"Fetching Block {BLOCK_HASH}...")
        block = substrate.get_block(block_hash=BLOCK_HASH)
        
        extrinsics = block['extrinsics']
        if EXTRINSIC_IDX >= len(extrinsics):
            print("Extrinsic index out of range")
            return
            
        extrinsic = extrinsics[EXTRINSIC_IDX]
        
        print("\n--- EXTRINSIC DETAILS ---")
        if hasattr(extrinsic, 'value'):
            val = extrinsic.value
        else:
            val = extrinsic
            
        # Try to access call details. might be obj or dict
        if hasattr(extrinsic, 'call'):
             call = extrinsic.call
             print(f"Module: {call.call_module.name}")
             print(f"Function: {call.call_function.name}")
             print(f"Args: {call.call_args}")
        else:
             call = val.get('call', {})
             print(f"Module: {call.get('call_module')}")
             print(f"Function: {call.get('call_function')}")
             print(f"Args: {call.get('call_args')}")

        print("\n--- EVENTS ---")
        events = substrate.get_events(block_hash=BLOCK_HASH)
        found = False
        for e in events:
            if hasattr(e, 'value'):
                ev = e.value
            else:
                ev = e
            
            # Check Extrinsic Index
            if ev.get('extrinsic_idx') == EXTRINSIC_IDX:
                found = True
                evt = ev.get('event', {})
                name = evt.get('event_id')
                module = evt.get('module_id')
                print(f"Event: {module}.{name}")
                if name == 'ExtrinsicSuccess':
                    print("✅ TRANSACTION SUCCESSFUL")
                elif name == 'ExtrinsicFailed':
                    # Extract error details
                    err_data = evt.get('attributes') or evt.get('data')
                    print(f"❌ TRANSACTION FAILED: {err_data}")

        if not found:
             # Fallback check for phase if extrinsic_idx is None (older behavior)
             for e in events:
                if hasattr(e, 'value'): ev = e.value
                else: ev = e
                phase = ev.get('phase')
                if isinstance(phase, dict) and phase.get('ApplyExtrinsic') == EXTRINSIC_IDX:
                    evt = ev.get('event', {})
                    name = evt.get('event_id')
                    module = evt.get('module_id')
                    print(f"Event: {module}.{name}")
                    if name == 'ExtrinsicSuccess':
                        print("✅ TRANSACTION SUCCESSFUL")
                    elif name == 'ExtrinsicFailed':
                         err_data = evt.get('attributes') or evt.get('data')
                         print(f"❌ TRANSACTION FAILED: {err_data}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()
