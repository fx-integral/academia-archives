# Note: Due to token limits, this script will be heavily relying on the Business API / AICenter for network traversal.
# In V2, the Validator connects to AICenter, gets the online hotkeys, sends active probes via AICenter, scores them, and submits to chain.
# (Code structure preserved and adapted for AICenter HTTP API)
import os
import sys
import time
import json
from datetime import datetime, timezone
import asyncio
import argparse
from pathlib import Path
import httpx
import bittensor as bt
from loguru import logger
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / 'configs' / 'validator.env')

env_map = {
    'BITTENSOR_NETUID': '--netuid',
    'BITTENSOR_NETWORK': '--subtensor.network',
    'WALLET_NAME': '--wallet.name',
    'WALLET_HOTKEY': '--wallet.hotkey',
    'VALID_MODEL_SERIES': '--valid.model_series',
}
for env_key, arg_flag in env_map.items():
    val = os.getenv(env_key)
    if val and arg_flag not in sys.argv:
        sys.argv.extend([arg_flag, val])


def verify_subtensor_connection(network: str, max_retries: int = 5, retry_delay: int = 5) -> bool:
    logger.info(f"🔌 Verifying connection to {network} network...")
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"   Attempt {attempt}/{max_retries}...")
            subtensor = bt.Subtensor(network=network)
            block = subtensor.get_current_block()
            if block > 0:
                logger.info(f"✅ Connected to {network} network (block {block})")
                return True
        except Exception as e:
            logger.warning(f"   Connection failed: {e}")
        if attempt < max_retries:
            time.sleep(retry_delay)
    return False

class V2Validator:
    def _setup_logging(self):
        logger.remove()
        # Silence websockets background thread spam (keepalive ping timeouts from Bittensor)
        import logging
        logging.getLogger("websockets").setLevel(logging.CRITICAL)
        logging.getLogger("websockets.client").setLevel(logging.CRITICAL)
        logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
        # Silence Python's default thread exception printing for websockets keepalive timeouts
        import threading
        import sys
        _original_thread_excepthook = threading.excepthook
        def _silent_ws_thread_excepthook(args):
            if args.exc_type and "ConnectionClosedError" in args.exc_type.__name__ and "keepalive" in str(args.exc_value):
                return
            if args.exc_type and "TimeoutError" in args.exc_type.__name__ and "closing connection" in str(args.exc_value):
                return
            _original_thread_excepthook(args)
        threading.excepthook = _silent_ws_thread_excepthook


        log_level = os.getenv('LOGGING_LEVEL', 'INFO').upper()
        log_debug = os.getenv('LOGGING_DEBUG', 'false').lower() == 'true'
        if log_debug:
            log_level = 'DEBUG'
            
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        
        # Add rolling file logger
        log_dir = Path(__file__).parent / 'logs'
        log_dir.mkdir(exist_ok=True)
        logger.add(
            log_dir / f"{Path(__file__).stem}-{{time:YYYYMMDD}}.log",
            rotation="00:00",
            retention="7 days",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )
    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        parser.add_argument('--netuid', type=int, default=1)
        parser.add_argument('--valid.model_series', type=str, default='gpt,qwen')
    
    def __init__(self):
        parser = argparse.ArgumentParser()
        bt.Wallet.add_args(parser)
        bt.Subtensor.add_args(parser)
        V2Validator.add_args(parser)
        self.config = bt.Config(parser)
        
        self.wallet = bt.Wallet(config=self.config)
        
        network = self.config.subtensor.network
        max_retries = int(os.getenv('SUBTENSOR_MAX_RETRIES', '5'))
        if not verify_subtensor_connection(network, max_retries, 5):
            logger.error(f"🚨 CRITICAL: Cannot connect to {network} network. Exiting.")
            sys.exit(1)
            
        self.subtensor = bt.Subtensor(config=self.config)
        
        # Initial sync with retries
        self.metagraph = None
        for attempt in range(3):
            try:
                logger.info(f"Syncing metagraph (netuid={self.config.netuid}, attempt {attempt+1}/3)...")
                self.metagraph = bt.Metagraph(netuid=self.config.netuid, network=self.subtensor.network, sync=True)
                break
            except Exception as e:
                logger.warning(f"Metagraph sync attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(5)
                else:
                    logger.warning("All sync attempts failed. Exiting.")
                    sys.exit(1)
                    
        
        self.aicenter_url = os.getenv("AICENTER_URL", "http://localhost:8000")
        self.api_key = os.getenv("NETWORK_API_KEY", "default_network_key")
        self.business_api_url = os.getenv("BUSINESS_API_URL", "http://localhost:8080")
        
        self.valid_model_series = []
        self.update_valid_model_series()
        self.miner_scores = {}
        self.last_sync_block = 0
        self.metagraph_sync_interval = 20
        self.last_weight_submit_block = self._load_last_weight_submit_block()
        
        self._setup_logging()
        logger.info(f"V2 Validator Initialized. Hotkey: {self.wallet.hotkey.ss58_address[:8]}...")



    def _load_last_weight_submit_block(self) -> int:
        state_file = Path(__file__).parent / '.validator_state.json'
        try:
            if state_file.exists():
                with open(state_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_weight_submit_block', 0)
        except Exception as e:
            logger.warning(f"Failed to load state file: {e}")
        return 0
    
    def _save_last_weight_submit_block(self, block: int):
        state_file = Path(__file__).parent / '.validator_state.json'
        try:
            with open(state_file, 'w') as f:
                json.dump({'last_weight_submit_block': block}, f)
            logger.debug(f"💾 Saved state: last_weight_submit_block={block}")
        except Exception as e:
            logger.error(f"Failed to save state file: {e}")

    def update_valid_model_series(self):
        url_or_list = self.config.valid.model_series
        if url_or_list.startswith('http://') or url_or_list.startswith('https://'):
            try:
                with httpx.Client(timeout=15.0) as client:
                    response = client.get(url_or_list)
                    if response.status_code == 200:
                        raw_text = response.text
                        models = []
                        for line in raw_text.replace(',', '\n').split('\n'):
                            clean_line = line.split('#')[0].strip().lower()
                            if clean_line:
                                models.append(clean_line)
                        if models:
                            if getattr(self, 'valid_model_series', None) != models:
                                logger.info(f"🔄 Hot-updated allowed models from URL: {models}")
                                self.valid_model_series = models
                        else:
                            logger.warning("⚠️ Fetched model list is empty, keeping previous list.")
                    else:
                        logger.warning(f"⚠️ Failed to fetch model list (HTTP {response.status_code}), keeping previous list.")
            except Exception as e:
                logger.warning(f"⚠️ Error fetching model whitelist from URL: {e}")
        else:
            self.valid_model_series = [m.strip().lower() for m in url_or_list.split(',') if m.strip()]

    def validate_model(self, model_name: str) -> bool:
        if not model_name: return False
        return any(series in model_name.lower() for series in self.valid_model_series)

    async def poll_miner_via_aicenter(self, hotkey: str, uid: int, client: httpx.AsyncClient):
        result = {'hotkey': hotkey, 'uid': uid, 'is_available': False, 'model_info': 'unknown', 'response_time_ms': 0}
        headers = {'Authorization': f'Bearer {self.api_key}'}
        
        try:
            # 1. Model Info
            start_time = time.time()
            resp = await client.post(f"{self.aicenter_url}/api/route/{hotkey}", 
                json={"timeout": 10.0, "payload": {"request_type": "model_info"}}, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    result['is_available'] = True
                    result['model_info'] = data.get('model_name', 'unknown')
                    result['response_time_ms'] = (time.time() - start_time) * 1000
                    
                    # 2. Active Probe
                    if self.validate_model(result['model_info']):
                        probe_start = time.time()
                        probe_resp = await client.post(f"{self.aicenter_url}/api/route/{hotkey}", 
                            json={"timeout": 8.0, "payload": {"request_type": "inference", "model": result['model_info'], "messages": [{"role": "system", "content": "You are a healthcheck bot. Reply strictly with the word pong. Do not use `<think>` tags."}, {"role": "user", "content": "ping"}], "max_tokens": 5, "temperature": 0.0}}, headers=headers)
                        
                        if probe_resp.status_code == 200 and probe_resp.json().get('success') and probe_resp.json().get('completion'):
                            result['response_time_ms'] = (time.time() - probe_start) * 1000
                            logger.debug(f"   ✅ Miner {hotkey[:8]}... (UID:{uid:3d}) passed V2 active probe.")
                        else:
                            result['is_available'] = False
                            logger.warning(f"   ⚠️ Miner {hotkey[:8]}... (UID:{uid:3d}) failed V2 active probe.")
        except Exception as e:
            logger.warning(f"   ⚠️ Miner {hotkey[:8]}... (UID:{uid:3d}) error during active probe: {e}")
            
        return result

    async def get_business_score(self, hotkey: str, uid: int, client: httpx.AsyncClient) -> tuple:
        try:
            resp = await client.post(
                f"{self.business_api_url}/scoring",
                json={'miner_hotkey': hotkey, 'miner_uid': uid, 'validator_hotkey': self.wallet.hotkey.ss58_address},
                headers={'Authorization': f'Bearer {self.api_key}'}
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get('contribution_score', 0.0), data
            else:
                logger.warning(f"Business API error {resp.status_code} for {hotkey[:8]}...")
        except Exception as e:
            logger.error(f"Failed to fetch business score for {hotkey[:8]}...: {e}")
        return 0.0, {}

    async def calculate_score(self, result: dict, client: httpx.AsyncClient) -> tuple:
        hotkey = result['hotkey']
        uid = result['uid']
        is_available = result['is_available']
        model_info = result['model_info']
        rt_ms = result['response_time_ms']
        
        has_valid_model = bool(is_available and model_info and model_info != 'unknown' and self.validate_model(model_info))
        
        if not hasattr(self, 'uptime_tracker'):
            self.uptime_tracker = {}
        if hotkey not in self.uptime_tracker:
            self.uptime_tracker[hotkey] = []
        self.uptime_tracker[hotkey].append(has_valid_model)
        if len(self.uptime_tracker[hotkey]) > 100:
            self.uptime_tracker[hotkey] = self.uptime_tracker[hotkey][-100:]
        
        uptime = sum(self.uptime_tracker[hotkey]) / len(self.uptime_tracker[hotkey]) * 100.0

        if not has_valid_model:
            return 0.0, {
                'uid': uid, 'hotkey': hotkey, 'model': model_info, 'rt_ms': rt_ms,
                'base': {'total': 0.0, 'model_score': 0.0, 'avail_score': 0.0, 'rt_score': 0.0, 'uptime_score': 0.0},
                'business': {'score': 0.0, 'total_requests': 0, 'total_tokens': 0, 'success_rate': 0.0}
            }

        business_score, b_data = await self.get_business_score(hotkey, uid, client)
        
        model_score = 100.0
        avail_score = 100.0
        rt_score = 100.0 if rt_ms < 100 else 80.0 if rt_ms < 500 else 60.0 if rt_ms < 1000 else 40.0 if rt_ms < 2000 else 20.0
        
        base_score = (model_score * 0.3) + (avail_score * 0.4) + (rt_score * 0.2) + (uptime * 0.1)
        final_score = (base_score * 0.1) + (business_score * 0.9)
        
        breakdown = {
            'uid': uid, 'hotkey': hotkey, 'model': model_info, 'rt_ms': rt_ms,
            'base': {
                'total': base_score, 'model_score': model_score, 'avail_score': avail_score, 
                'rt_score': rt_score, 'uptime_score': uptime
            },
            'business': {
                'score': business_score, 'total_requests': b_data.get('total_requests', 0), 
                'total_tokens': b_data.get('total_tokens', 0), 'success_rate': b_data.get('success_rate', 0.0)
            }
        }
        return final_score, breakdown

    async def submit_weights(self):
        if not hasattr(self, 'miner_scores') or not self.miner_scores:
            return
            
        current_block = self.subtensor.get_current_block()
        blocks_since_submit = current_block - getattr(self, 'last_weight_submit_block', 0)
        
        weight_interval = int(os.getenv('WEIGHT_SUBMIT_INTERVAL', '20'))
        if blocks_since_submit < weight_interval:
            logger.info(f"⏱️ Weights: submitted at block {getattr(self, 'last_weight_submit_block', 0)}, next in ~{weight_interval - blocks_since_submit} blocks")
            return
            
        logger.info(f"⚖️ WEIGHT SUBMIT TRIGGERED | block {current_block}")
        
        uids = []
        weights = []
        for hk, score in self.miner_scores.items():
            if hk in self.metagraph.hotkeys:
                uid = self.metagraph.hotkeys.index(hk)
                uids.append(uid)
                weights.append(score)
                
        if not uids:
            return
            
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
            
        # Prepare and sort data for WEIGHTS.log
        combined = list(zip(uids, weights))
        combined.sort(key=lambda x: x[0])
            
        logger.info(f"⚖️ Submitting weights for {len(uids)} miners...")
        
        try:
            success = self.subtensor.set_weights(
                wallet=self.wallet, netuid=self.config.netuid, uids=uids, weights=weights,
                version_key=1, wait_for_inclusion=False, wait_for_finalization=False
            )
            # Handle return tuple if needed
            if isinstance(success, tuple):
                success, msg = success
            
            
            # Determine true boolean success since Bittensor might return an ExtrinsicResponse object
            is_success = False
            if hasattr(success, 'success'):
                is_success = success.success
            elif isinstance(success, tuple) and len(success) > 0 and hasattr(success[0], 'success'):
                is_success = success[0].success
            else:
                is_success = bool(success)
                
            if is_success:
                self.last_weight_submit_block = current_block
                self._save_last_weight_submit_block(current_block)
                logger.success(f"⚖️ WEIGHTS SUBMITTED ✅ | block {current_block}")
            else:
                logger.error("⚖️ WEIGHTS SUBMIT FAILED ❌")
                
            # Log to WEIGHTS.log
            log_dir = Path(__file__).parent / 'logs'
            log_dir.mkdir(exist_ok=True)
            with open(log_dir / 'WEIGHTS.log', 'a') as f:
                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                f.write(f"\n[{timestamp}] BLOCK: {current_block} | SUCCESS: {is_success}\n")
                f.write("-" * 45 + "\n")
                for u, w in combined:
                    f.write(f"UID: {u:4d} | WEIGHT: {w:.5f}\n")
                f.write("=" * 45 + "\n")
                
        except Exception as e:
            logger.error(f"Weight submission exception: {e}")
            
            # Log exception to WEIGHTS.log
            log_dir = Path(__file__).parent / 'logs'
            log_dir.mkdir(exist_ok=True)
            with open(log_dir / 'WEIGHTS.log', 'a') as f:
                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                f.write(f"\n[{timestamp}] BLOCK: {current_block} | SUCCESS: False (Exception)\n")
                f.write(f"ERROR: {e}\n")
                f.write("=" * 45 + "\n")

    async def run_round(self):
        current_block = self.subtensor.get_current_block()
        blocks_since_sync = current_block - self.last_sync_block if self.last_sync_block > 0 else 999
        
        if blocks_since_sync >= self.metagraph_sync_interval:
            if self.config.valid.model_series.startswith('http'):
                self.update_valid_model_series()
            logger.info(f"🔄 Syncing metagraph (every {self.metagraph_sync_interval} blocks)...")
            try:
                # Metagraph sync is synchronous and heavy. Run it in a separate thread so it doesn't freeze the asyncio loop.
                await asyncio.to_thread(self.metagraph.sync, subtensor=self.subtensor)
                self.last_sync_block = self.subtensor.get_current_block()
                logger.info(f"✅ Metagraph sync complete at block {self.last_sync_block}")
            except Exception as e:
                logger.error(f"❌ Metagraph sync failed: {e}")
        else:
            logger.info(f"⏭️ Skipping metagraph sync (next sync in {self.metagraph_sync_interval - blocks_since_sync} blocks)")
        
        logger.info(f"Fetching online miners from AICenter ({self.aicenter_url})...")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.aicenter_url}/api/online", headers={'Authorization': f'Bearer {self.api_key}'})
                if resp.status_code != 200:
                    logger.error(f"Failed to fetch online miners from AICenter (Status: {resp.status_code})")
                    return
                online_hotkeys = resp.json().get('hotkeys', [])
        except Exception as e:
            logger.error(f"❌ Could not connect to AICenter: {e}. Is aicenter.py running on {self.aicenter_url}?")
            logger.info("   Retrying in 60 seconds...")
            return
        
        logger.info(f"Found {len(online_hotkeys)} online hotkeys in AICenter")
        
        tasks = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for uid, hotkey in enumerate(self.metagraph.hotkeys):
                if hotkey in online_hotkeys:
                    tasks.append(self.poll_miner_via_aicenter(hotkey, uid, client))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                valid_results = [r for r in results if not isinstance(r, Exception)]
                valid_results.sort(key=lambda x: x.get('uid', 9999))
                
                self.miner_scores = {}
                scored_miners = []
                
                for res in valid_results:
                    # Aesthetic ordered logging for poll completion
                    uid_padded = f"{res.get('uid', 0):3d}"
                    if res.get('is_available'):
                        logger.debug(f"Polled miner {res.get('hotkey', '')[:8]}... (UID:{uid_padded}) - available=True, model={res.get('model_info', '')}, time={res.get('response_time_ms', 0):.2f}ms")
                    else:
                        logger.debug(f"Polled miner {res.get('hotkey', '')[:8]}... (UID:{uid_padded}) - no response or invalid model")
                        
                    score, breakdown = await self.calculate_score(res, client)
                    self.miner_scores[res['hotkey']] = score
                    if score > 0:
                        scored_miners.append({'score': score, 'breakdown': breakdown})
                        
                logger.info(f"=== Scoring Results ({len(scored_miners)} miners with score > 0) ===")
                for m in sorted(scored_miners, key=lambda x: x['score'], reverse=True):
                    b = m['breakdown']
                    b_score = b['business']['score']
                    logger.info(f"  UID:{b['uid']:3d} | {b['hotkey'][:8]}... | score={m['score']:6.2f} | model={b['model']:<20} | time={b['rt_ms']:.0f}ms")
                    logger.debug(f"    Base Score ({b['base']['total']:.2f} × 10% = {b['base']['total']*0.1:.2f}):")
                    logger.debug(f"      Model:  {b['base']['model_score']:5.1f} × 0.3 | Avail: {b['base']['avail_score']:5.1f} × 0.4")
                    logger.debug(f"      RT:     {b['base']['rt_score']:5.1f} × 0.2 | Uptime: {b['base']['uptime_score']:5.1f} × 0.1")
                    logger.debug(f"    🏢 Business Score ({b_score:.2f} × 90% = {b_score*0.9:.2f}):")
                    logger.debug(f"      Requests: {b['business']['total_requests']} | Tokens: {b['business']['total_tokens']} | Success: {b['business']['success_rate']:.1f}%")
                    logger.debug(f"    📊 Final: {b['base']['total']:.2f} × 0.1 + {b_score:.2f} × 0.9 = {m['score']:.2f}")
                
                await self.submit_weights()
            else:
                logger.warning("No online miners found to poll.")
                
        logger.info("V2 Polling round complete.")

    def run(self):
        self.poll_interval = int(os.getenv('VALIDATOR_POLL_INTERVAL', '300'))
        while True:
            try:
                asyncio.run(self.run_round())
                
                # Print countdown
                current_block = self.subtensor.get_current_block()
                blocks_since_sync = current_block - self.last_sync_block if self.last_sync_block > 0 else 0
                blocks_since_weight = current_block - getattr(self, 'last_weight_submit_block', 0) if getattr(self, 'last_weight_submit_block', 0) > 0 else 0
                blocks_until_sync = max(0, self.metagraph_sync_interval - blocks_since_sync)
                blocks_until_weight = max(0, int(os.getenv('WEIGHT_SUBMIT_INTERVAL', '20')) - blocks_since_weight)
                
                logger.info(f"⏱ Next poll in {self.poll_interval}s | [Block: {current_block}] Metagraph sync next {blocks_until_sync} blocks | Weight submit next {blocks_until_weight} blocks")
            except Exception as e:
                logger.error(f"Critical loop error: {e}. Attempting to reconnect to Subtensor...")
                try:
                    # Attempt to re-establish broken subtensor connections
                    self.subtensor = bt.Subtensor(config=self.config)
                except Exception as reconnect_e:
                    logger.error(f"Failed to reconnect: {reconnect_e}")
                    
            try:
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self.stop()
                break

    def stop(self):
        logger.info("Stopping V2 validator...")
        if hasattr(self, 'subtensor'):
            self.subtensor.close()
            logger.info("Subtensor connection closed")

if __name__ == '__main__':
    V2Validator().run()
