import unittest

import bittensor as bt
from prettytable import PrettyTable
class TestMiner(unittest.TestCase):

    def test_metagrash(self):
        sub = bt.subtensor(network='test')
        mg = bt.metagraph(netuid=374, network='test')
        mg.sync(subtensor=sub)

        i = 0
        validator = mg.validator_permit
        stake = mg.stake
        vtrust = mg.validator_trust
        trust = mg.trust
        consensus = mg.consensus
        incentive = mg.incentive
        dividends = mg.dividends
        emission = mg.emission
        update = mg.last_update
        alpha_stake = mg.alpha_stake
        active = mg.active
        table = PrettyTable(["Active","isServing", "UID", "TYPE", "Stake Weight", "VTrust", "Trust", "Consensus", "Incentive", "Dividends", "Emission", "Updated", "Axon", "Port", "HotKey", "ColdKey", "AlphaStake"])
        for axon in mg.axons:
            type = "Miner"
            if validator[i] :
                type = "Validator"

            table.add_row([active[i], mg.axons[i].is_serving, i, type, stake[i], vtrust[i], trust[i], consensus[i], incentive[i], dividends[i], emission[i], update[i], axon.ip, axon.port, "", "", alpha_stake[i]])
            i = i + 1

        print(table)

        pass

    def test_weights(self):
        mg = bt.Metagraph(netuid=374, network='test')
        print("weights:\n", mg.weights)