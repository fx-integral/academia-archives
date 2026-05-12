## change neurons/miner.py#L30
## from bitsec.miner.predict import predict
## to
## from bitsec.dummy_miner.predict import predict

python -m neurons.miner --netuid 209 --subtensor.chain_endpoint test --wallet.name miner2 --wallet.hotkey default --axon.port 8093 --axon.external_port 8093 --logging.debug