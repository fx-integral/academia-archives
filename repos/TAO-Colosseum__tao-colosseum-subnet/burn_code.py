import time
import argparse

import bittensor as bt
from bittensor_wallet import Wallet

MAINNET_NETUID = 79
BLOCK_TIME = 12


class TempValidator:
    def __init__(self):
        self.config = self.get_config()

        # Initialize wallet.
        self.wallet = Wallet(config=self.config)
        print(f"Wallet: {self.wallet}")

        # Initialize subtensor.
        self.subtensor = bt.subtensor(config=self.config)
        print(f"Subtensor: {self.subtensor}")

    def get_config(self):
        # Set up the configuration parser.
        parser = argparse.ArgumentParser(
            description="Temp SN79 Validator",
            usage="python3 sn79_temp_vali.py <command> [options]",
            add_help=True,
        )
        command_parser = parser.add_subparsers(dest="command")
        run_command_parser = command_parser.add_parser(
            "run", help="""Run the validator"""
        )

        # Adds override arguments for network and netuid.
        run_command_parser.add_argument(
            "--netuid", type=int, default=MAINNET_NETUID, help="The chain subnet uid."
        )

        run_command_parser.add_argument(
            "--set_weights_interval",
            type=int,
            default=360 * 2,  # 2 epochs
            help="The interval to set weights in blocks.",
        )

        # Adds subtensor specific arguments.
        bt.subtensor.add_args(run_command_parser)
        # Adds wallet specific arguments.
        Wallet.add_args(run_command_parser)

        # Parse the config.
        try:
            config = bt.config(parser)
        except ValueError as e:
            print(f"Error parsing config: {e}")
            exit(1)

        return config

    def get_burn_uid(self):
        # Get the subtensor owner hotkey
        sn_owner_hotkey = self.subtensor.query_subtensor(
            "SubnetOwnerHotkey",
            params=[self.config.netuid],
        )
        print(f"SN Owner Hotkey: {sn_owner_hotkey}")

        # Get the UID of this hotkey
        sn_owner_uid = self.subtensor.get_uid_for_hotkey_on_subnet(
            hotkey_ss58=sn_owner_hotkey,
            netuid=self.config.netuid,
        )
        print(f"SN Owner UID: {sn_owner_uid}")

        return sn_owner_uid

    def run(self):
        print("Running validator...")

        while True:
            print("Running validator loop...")

            # Check if registered.
            registered = self.subtensor.is_hotkey_registered_on_subnet(
                hotkey_ss58=self.wallet.hotkey.ss58_address,
                netuid=self.config.netuid,
            )
            print(f"Registered: {registered}")

            if not registered:
                print("Not registered, skipping...")
                time.sleep(10)
                continue

            # Check Validator Permit
            validator_permits = self.subtensor.query_subtensor(
                "ValidatorPermit",
                params=[self.config.netuid],
            ).value
            this_uid = self.subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=self.wallet.hotkey.ss58_address,
                netuid=self.config.netuid,
            )
            print(f"Validator UID: {this_uid}")
            print(f"Validator Permit: {validator_permits[this_uid]}")
            if not validator_permits[this_uid]:
                print("No Validator Permit, wait until next epoch...")
                curr_block = self.subtensor.get_current_block()
                tempo = self.subtensor.query_subtensor(
                    "Tempo",
                    params=[self.config.netuid],
                ).value
                print(f"Tempo: {tempo}")
                blocks_since_last_step = self.subtensor.query_subtensor(
                    "BlocksSinceLastStep",
                    block=curr_block,
                    params=[self.config.netuid],
                ).value
                print(f"Blocks Since Last Step: {blocks_since_last_step}")
                time_to_wait = (tempo - blocks_since_last_step) * BLOCK_TIME + 0.1
                print(f"Sleeping until next epoch, {time_to_wait} seconds...")
                time.sleep(time_to_wait)
                continue

            # Get the weights version key.
            version_key = self.subtensor.query_subtensor(
                "WeightsVersionKey",
                params=[self.config.netuid],
            ).value
            print(f"Weights Version Key: {version_key}")

            # Get the burn UID.
            burn_uid = self.get_burn_uid()
            subnet_n = self.subtensor.query_subtensor(
                "SubnetworkN",
                params=[self.config.netuid],
            ).value
            print(f"Subnet N: {subnet_n}")

            # Set weights to burn UID.
            uids = [burn_uid]
            weights = [1.0]

            # Set weights.
            success, message = self.subtensor.set_weights(
                self.wallet,
                self.config.netuid,
                uids,
                weights,
                version_key=version_key,
                wait_for_inclusion=True,
                wait_for_finalization=True,
            )
            if not success:
                print(f"Error setting weights: {message}")
                time.sleep(10)
                continue

            print("Weights set.")

            # Wait for next time to set weights.
            print(
                f"Waiting {self.config.set_weights_interval} blocks before next weight set..."
            )
            time.sleep(self.config.set_weights_interval * BLOCK_TIME)


if __name__ == "__main__":
    validator = TempValidator()
    validator.run()