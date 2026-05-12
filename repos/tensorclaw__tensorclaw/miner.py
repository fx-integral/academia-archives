import os
import sys
import time
import json
import asyncio
import argparse
from pathlib import Path
import aiohttp
import websockets
import bittensor as bt
from loguru import logger
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / 'configs' / 'miner.env')

# Inject env vars to sys.argv
env_map = {
    'WALLET_NAME': '--wallet.name',
    'WALLET_HOTKEY': '--wallet.hotkey',
    'MODEL_URL': '--model.url',
    'MODEL_NAME': '--model.name',
    'MODEL_API_KEY': '--model.api_key',
}
for env_key, arg_flag in env_map.items():
    val = os.getenv(env_key)
    if val and arg_flag not in sys.argv:
        sys.argv.extend([arg_flag, val])


class V2Miner:
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
        parser.add_argument('--netuid', type=int, default=1, help='Subnet netuid')
        bt.Subtensor.add_args(parser)
        parser.add_argument('--model.url', type=str, default='http://localhost:8000/v1', help='Model API URL')
        parser.add_argument('--model.name', type=str, default='qwen3.5:9b', help='Model name')
        parser.add_argument('--model.api_key', type=str, default='', help='Model API key')
    
    def __init__(self):
        parser = argparse.ArgumentParser()
        bt.Wallet.add_args(parser)
        V2Miner.add_args(parser)
        self.config = bt.Config(parser)
        
        self.model_url = self.config.model.url
        self.model_name = self.config.model.name
        self.model_api_key = self.config.model.api_key
        self.wallet = bt.Wallet(config=self.config)
        self.hotkey = self.wallet.hotkey.ss58_address
        
        self.aicenter_ws_url = os.getenv("AICENTER_WS_URL", "ws://localhost:8000")
        self.api_key = os.getenv("NETWORK_API_KEY", "default_network_key")
        
        self._setup_logging()
        logger.info(f"V2 Miner Initialized. Hotkey: {self.hotkey[:8]}...")
        
        # Determine UID on the subnet
        try:
            logger.info(f"Connecting to {self.config.subtensor.network} to resolve UID for netuid {self.config.netuid}...")
            subtensor = bt.Subtensor(config=self.config)
            uid = subtensor.get_uid_for_hotkey_on_subnet(self.hotkey, self.config.netuid)
            if uid is not None:
                logger.success(f"🎯 Miner registered on Subnet {self.config.netuid} with UID: {uid}")
            else:
                logger.warning(f"⚠️ Miner is NOT registered on Subnet {self.config.netuid} yet!")
        except Exception as e:
            logger.warning(f"⚠️ Could not resolve UID from Subtensor: {e}")
        
        # Local Statistics Tracking
        self.request_count = 0
        self.info_count = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        logger.info(f"Model: {self.model_name} @ {self.model_url}")
        
    async def process_inference(self, payload: dict, trace_id: str) -> dict:
        start_time = time.time()
        
        # V1 Log Parity
        messages = payload.get('messages', [])
        logger.info(f"🤖 Inference request received")
        logger.info(f"   Trace ID:   {trace_id}")
        logger.debug(f"   Model:      {payload.get('model', self.model_name)}")
        logger.debug(f"   Messages:   {len(messages)} messages")
        logger.debug(f"   First msg:  {messages[0] if messages else 'N/A'}")
        logger.debug(f"   Max Tokens: {payload.get('max_tokens', 1024)}, Temp: {payload.get('temperature', 0.0)}")
        logger.debug(f"   Target URL: {self.model_url}/chat/completions")
        
        self.request_count += 1
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'Content-Type': 'application/json'}
                if self.model_api_key:
                    headers['Authorization'] = f'Bearer {self.model_api_key}'
                
                body = {
                    'model': payload.get('model', self.model_name),
                    'messages': messages,
                    'temperature': payload.get('temperature', 0.7),
                    'stream': False # Explicitly disable streaming for standard REST endpoints
                }
                
                # Only inject max_tokens if explicitly requested and safe, otherwise let the backend engine decide safely.
                if payload.get('max_tokens'):
                    body['max_tokens'] = payload.get('max_tokens')
                else:
                    body['max_tokens'] = 16384 # Override default Ollama 4096 cutoff for long responses
                    
                # Passthrough any extra OpenAI parameters (like top_p, frequency_penalty, tools, etc.)
                for k, v in payload.items():
                    if k not in ['request_type', 'trace_id', 'model', 'messages', 'temperature', 'max_tokens', 'stream']:
                        body[k] = v
                
                async with session.post(f"{self.model_url}/chat/completions", json=body, headers=headers, timeout=120.0) as resp:
                    resp_time = (time.time() - start_time) * 1000
                    try:
                        response_data = await resp.json()
                    except:
                        response_data = {"error": await resp.text()}
                    
                    if resp.status >= 400 and resp.status < 500:
                        logger.warning(f"   ⚠️ Client Error {resp.status} from backend API: {str(response_data)[:200]}")
                        return {
                            "success": False, 
                            "is_client_error": True, 
                            "status_code": resp.status, 
                            "error_message": response_data
                        }
                    
                    logger.debug(f"   Backend response keys: {list(response_data.keys())}")
                    
                    # ⚠️ CRITICAL V1 PARITY: Token Extraction
                    usage = response_data.get('usage', {})
                    tokens_in = usage.get('prompt_tokens', 0)
                    tokens_out = usage.get('completion_tokens', 0)
                    
                    self.total_tokens_in += tokens_in
                    self.total_tokens_out += tokens_out
                    
                    if 'choices' in response_data and len(response_data['choices']) > 0:
                        choice = response_data['choices'][0]
                        message = choice.get('message', {})
                        
                        content = ''
                        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
                        base_content = message.get('content') or choice.get('text') or choice.get('output') or choice.get('completion') or ''
                        
                        if reasoning and base_content:
                            content = f"<think>\n{reasoning}\n</think>\n\n{base_content}"
                        elif base_content:
                            content = base_content
                        elif reasoning:
                            content = f"<think>\n{reasoning}\n</think>"
                            
                        if not content:
                            # It is completely possible for a model to return an empty string if it generated a zero-token response or max_tokens forced a weird cutoff.
                            # But we shouldn't fail the request. We should just return the empty string so the frontend doesn't crash.
                            logger.warning(f"   ⚠️ Empty content from backend API. Treating as valid empty response.")
                            content = "" 
                            
                        logger.debug(f"   Response Content Preview: {content[:100]}...")
                        logger.info(f"   ✅ Processed in {resp_time:.0f}ms | Tokens: {tokens_in} in, {tokens_out} out")
                        return {
                            "success": True,
                            "completion": content,
                            "response_data": response_data,
                            "response_time_ms": resp_time,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out
                        }
                    else:
                        logger.warning(f"   ⚠️ API returned no choices: {str(response_data)[:100]}")
                        return {"success": False, "error_message": str(response_data)}
        except Exception as e:
            logger.error(f"   ❌ Inference error: {e}")
            return {"success": False, "error_message": str(e)}

    async def connect_and_listen(self):
        base_url = self.aicenter_ws_url.rstrip('/')
        ws_url = f"{base_url}/ws/miner/{self.hotkey}?api_key={self.api_key}"
        
        while True:
            try:
                logger.info(f"🔌 Connecting to AICenter: {self.aicenter_ws_url}")
                async with websockets.connect(ws_url, ping_interval=None) as ws:
                    logger.success("✅ Connected to AICenter successfully!")
                    while True:
                        # Client-side zombie detection: If we don't hear anything (not even a ping) 
                        # for 60 seconds, the connection is dead. Force a reconnect.
                        msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                        try:
                            data = json.loads(msg)
                            msg_type = data.get("type")
                            if msg_type == "ping":
                                await ws.send(json.dumps({"type": "pong"}))
                            elif msg_type == "request":
                                trace_id = data.get("trace_id")
                                payload = data.get("payload", {})
                                req_type = payload.get("request_type")
                                
                                if req_type == "model_info":
                                    self.info_count += 1
                                    logger.info(f"📋 Info request received from AICenter")
                                    logger.info(f"   Model Name: {self.model_name}")
                                    logger.info(f"   ✅ Sent model info back")
                                    resp_data = {
                                        "success": True,
                                        "model_name": self.model_name,
                                        "model_url": self.model_url,
                                        "is_available": True
                                    }
                                    await ws.send(json.dumps({"type": "response", "trace_id": trace_id, "data": resp_data}))
                                elif req_type == "inference":
                                    resp_data = await self.process_inference(payload, trace_id)
                                    await ws.send(json.dumps({"type": "response", "trace_id": trace_id, "data": resp_data}))
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
            except asyncio.TimeoutError:
                logger.error("🔴 Server stopped responding to pings (Zombie connection). Forcing reconnect...")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("🔴 Connection closed. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"🔴 Connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    def run(self):
        try:
            asyncio.run(self.connect_and_listen())
        except KeyboardInterrupt:
            logger.info("Miner stopped by user")

if __name__ == "__main__":
    V2Miner().run()
