import bittensor as bt
import pyotp
import asyncio
import hashlib
import base64

from merit.protocol.merit_protocol import PingSynapse
from merit.config import merit_config

class Miner:
    def __init__(self, config: bt.Config):
        bt.logging.info("Initializing Miner...")

        self.wallet = bt.wallet(config=config)
        self.subtensor = bt.subtensor(config=config)
        self.netuid = config.netuid

        self.axon = bt.axon(wallet=self.wallet, config=config)

        # Hotkey registration check
        self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
        if self.wallet.hotkey.ss58_address not in self.metagraph.hotkeys:
            bt.logging.error(f"Hotkey {self.wallet.hotkey.ss58_address} is not registered on subnet {self.netuid}. Exiting.")
            exit(1)

        # Attach forward function
        self.axon.attach(self.handle_ping_request)

        # Start local axon server
        self.axon.start()
        bt.logging.success(f"Miner Axon started at {self.axon.external_ip}:{self.axon.external_port}")

        self.subtensor.serve_axon(
            axon=self.axon,
            netuid=self.netuid,
        )
        bt.logging.success(f"Miner served on netuid {self.netuid}.")

    async def handle_ping_request(self, synapse: PingSynapse) -> PingSynapse:
        hotkey = self.wallet.hotkey.ss58_address
        # Generate TOTP token based on hotkey
        hashed = hashlib.sha256(hotkey.encode('utf-8')).digest()
        base32_secret = base64.b32encode(hashed).decode('utf-8').strip('=')
        totp = pyotp.TOTP(base32_secret)
        token = totp.now()

        bt.logging.debug(f"[Miner] Sending PingResponse: hotkey={hotkey}, token={token}")
        synapse.token = token
        return synapse

    async def _periodic_registration_check(self, interval_seconds: int = 1800):
        while True:
            try:
                self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
                hotkey = self.wallet.hotkey.ss58_address

                if hotkey not in self.metagraph.hotkeys:
                    bt.logging.error(f"❌ Miner hotkey {hotkey} is no longer registered on subnet {self.netuid}. "
                                     f"Exiting.")
                    self.axon.stop()
                    exit(1)
                else:
                    bt.logging.debug(f"✅ Miner hotkey {hotkey} still registered on subnet {self.netuid}.")
            except Exception as e:
                bt.logging.error(f"⚠️ Registration check failed: {e}")

            await asyncio.sleep(interval_seconds)

    def run(self):
        """
        Runs the miner indefinitely.
        """
        bt.logging.info("Miner running...")
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._periodic_registration_check())
            loop.run_forever()
        except KeyboardInterrupt:
            bt.logging.warning("Miner shutting down...")
            self.axon.stop()
            bt.logging.warning("Miner shutdown complete.")
