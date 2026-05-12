import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import pandas as pd
import utils.logger as logger
import validator.config as config
from datetime import datetime
from bittensor.core.async_subtensor import AsyncSubtensor
from dotenv import load_dotenv
load_dotenv(dotenv_path="validator/.env")

async def get_subnet_info():
    """Get comprehensive subnet information."""
    subtensor = AsyncSubtensor(
        network=config.SUBTENSOR_NETWORK,
        fallback_endpoints=[config.SUBTENSOR_ADDRESS]
    )
    
    try:        
        metagraph = await subtensor.metagraph(netuid=config.NETUID, lite=False)
        await metagraph.sync()
        total_nodes = len(metagraph.neurons)
        total_stake = sum(float(n.stake) for n in metagraph.neurons)
        tempo = await subtensor.tempo(netuid=config.NETUID)

        nodes = []
        for neuron in metagraph.neurons:
            nodes.append({
                "uid": neuron.uid,
                "hotkey": neuron.hotkey,
                "coldkey": neuron.coldkey,
                "stake": float(neuron.stake),
                "last_update": neuron.last_update,
                "emission": neuron.emission,
                "incentive": neuron.incentive,
                "consensus": neuron.consensus,
                "validator_trust": neuron.validator_trust,
                "v_permit": neuron.validator_permit,
                "ip": neuron.axon_info.ip if neuron.axon_info else None,
                "port": neuron.axon_info.port if neuron.axon_info else None,
            })
        
        return {
            "total_nodes": total_nodes,
            "total_stake": total_stake,
            "nodes": nodes,
            "netuid": config.NETUID,
            "tempo": tempo,
            "weights": metagraph.weights.tolist() if metagraph.weights is not None else None,
        }
    finally:
        # Clean up
        if hasattr(subtensor, 'close'):
            await subtensor.close()

def display_subnet_info(info: dict):
    """Display subnet information in organized tables."""
    print("\n" + "="*80)
    print(f"SUBNET {info['netuid']} OVERVIEW".center(80))
    print("="*80)
    
    # Summary statistics
    summary_df = pd.DataFrame([{
        'Total Nodes': info['total_nodes'],
        'Total Stake (τ)': f"{info['total_stake']:,.2f}",
        'Avg Stake (τ)': f"{info['total_stake']/info['total_nodes']:,.2f}",
    }])
    print("\n" + summary_df.to_string(index=False))    
    
    df = pd.DataFrame(info['nodes'])    
    
    df['stake_tao'] = df['stake'].apply(lambda x: f"{x:,.2f}")
    
    # Add time-based columns
    if len(df) > 0:
        current_block = df['last_update'].max()
        df['blocks_ago'] = current_block - df['last_update']
        df['hours_ago'] = (df['blocks_ago'] * 12 / 3600).round(1)
    
    # Top 10 by stake
    print("\n" + "="*80)
    print("TOP 10 NODES BY STAKE".center(80))
    print("="*80)
    top_10 = df.nlargest(10, 'stake')[['uid', 'hotkey', 'stake_tao', 'hours_ago', 'last_update']]
    top_10.columns = ['UID', 'Hotkey', 'Stake (τ)', 'Hours Ago', 'Block']
    print("\n" + top_10.to_string(index=False))
    
    # Stake distribution
    print("\n" + "="*80)
    print("STAKE DISTRIBUTION".center(80))
    print("="*80)
    
    stake_ranges = [
        (0, 1, "0-1 τ"),
        (1, 100, "1-100 τ"),
        (100, 1000, "100-1k τ"),
        (1000, 10000, "1k-10k τ"),
        (10000, 50000, "10k-50k τ"),
        (50000, 100000, "50k-100k τ"),
        (100000, float('inf'), "100k+ τ")
    ]
    
    dist_data = []
    for min_stake, max_stake, label in stake_ranges:
        count = len(df[(df['stake'] >= min_stake) & (df['stake'] < max_stake)])
        if count > 0:
            dist_data.append({'Range': label, 'Count': count})
    
    dist_df = pd.DataFrame(dist_data)
    print("\n" + dist_df.to_string(index=False))
    
    # Nodes with zero stake
    zero_stake = df[df['stake'] == 0.0]
    print("\n" + "="*80)
    print(f"ZERO STAKE NODES: {len(zero_stake)} ({len(zero_stake)/len(df)*100:.1f}%)".center(80))
    print("="*80)
    
    # Recent activity (last 1000 blocks ~ 3.3 hours at 12s block time)
    if len(df) > 0:
        max_block = df['last_update'].max()
        recent_threshold = max_block - 1000
        recent_nodes = df[df['last_update'] >= recent_threshold]
        
        print("\n" + "="*80)
        print(f"RECENTLY ACTIVE (last ~3 hours): {len(recent_nodes)} nodes".center(80))
        print("="*80)
    
    # Full list option
    print("\n" + "="*80)
    response = input("Show full node list? (y/n): ").strip().lower()
    if response == 'y':
        full_df = df[['uid', 'hotkey', 'coldkey', 'stake_tao', 'hours_ago', 'last_update']]
        full_df.columns = ['UID', 'Hotkey', 'Coldkey', 'Stake (τ)', 'Hours Ago', 'Block']
        print("\n" + full_df.to_string(index=False))
    
    print("\n" + "="*80)


def write_subnet_info(info: dict, filename: str = "subnet_info.json"):
    """Write subnet information to a JSON file."""
    import json
    with open(filename, 'w') as f:
        json.dump(info, f, indent=4)
    logger.info(f"Subnet information written to {filename}")


if __name__ == "__main__":
    info = asyncio.run(get_subnet_info())
    display_subnet_info(info)
    info_name = f"subnet_{info['netuid']}_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_subnet_info(info, info_name)
    print(f"Subnet information retrieval completed. Data saved to {info_name}")
