import asyncio
import random
import time
from typing import List

import bittensor as bt
import numpy as np
from PIL import Image


def create_random_image():
    random_data = np.random.randint(0, 256, (512, 512, 3), dtype=np.uint8)
    return Image.fromarray(random_data)


class MockSubtensor(bt.MockSubtensor):
    def __init__(self, netuid, n=16, wallet=None, network="mock"):
        super().__init__(network=network)
        bt.MockSubtensor.reset()

        if not self.subnet_exists(netuid):
            self.create_subnet(netuid)

        if wallet is not None:
            try:
                self.force_register_neuron(
                    netuid=netuid,
                    hotkey=wallet.hotkey.ss58_address,
                    coldkey=wallet.coldkey.ss58_address,
                    balance=100000,
                    stake=100000,
                )
            except Exception as e:
                print(f"Skipping force_register_neuron: {e}")

        for i in range(1, n + 1):
            try:
                self.force_register_neuron(
                    netuid=netuid,
                    hotkey=f"miner-hotkey-{i}",
                    coldkey="mock-coldkey",
                    balance=100000,
                    stake=100000,
                )
            except Exception as e:
                print(f"Skipping force_register_neuron: {e}")


class MockMetagraph(bt.metagraph):
    def __init__(self, netuid, network="mock", subtensor=None):
        super().__init__(netuid=netuid, network=network, sync=False)
        self.default_ip = "127.0.0.0"
        self.default_port = 8092

        if subtensor is not None:
            self.subtensor = subtensor
        self.sync(subtensor=subtensor)

        for axon in self.axons:
            axon.ip = self.default_ip
            axon.port = self.default_port

        bt.logging.info(f"Metagraph: {self}")
        bt.logging.info(f"Axons: {self.axons}")


class MockDendrite(bt.dendrite):
    """Replaces real bittensor network requests with static mock responses."""

    def __init__(self, wallet):
        super().__init__(wallet)

    async def forward(
        self,
        axons: List[bt.axon],
        synapse: bt.Synapse = bt.Synapse(),
        timeout: float = 12,
        deserialize: bool = True,
        run_async: bool = True,
        streaming: bool = False,
    ):
        if streaming:
            raise NotImplementedError("Streaming not implemented yet.")

        async def query_all_axons(streaming: bool):
            async def single_axon_response(i, axon):
                start_time = time.time()
                s = synapse.copy()
                s = self.preprocess_synapse_for_request(axon, s, timeout)
                process_time = random.random()
                if process_time < timeout:
                    s.dendrite.process_time = str(time.time() - start_time)
                    s.prediction = np.random.rand(1)[0]
                    s.dendrite.status_code = 200
                    s.dendrite.status_message = "OK"
                    s.dendrite.process_time = str(process_time)
                else:
                    s.prediction = -1
                    s.dendrite.status_code = 408
                    s.dendrite.status_message = "Timeout"
                    s.dendrite.process_time = str(timeout)
                return s.deserialize() if deserialize else s

            return await asyncio.gather(*(single_axon_response(i, axon) for i, axon in enumerate(axons)))

        return await query_all_axons(streaming)

    def __str__(self) -> str:
        return "MockDendrite({})".format(self.keypair.ss58_address)
