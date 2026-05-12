import bittensor as bt
import pyotp
import asyncio
import os
import json
import hashlib
import base64
import ipaddress
import time
from merit.protocol.merit_protocol import PingSynapse
from merit.config import merit_config

class Validator:
    def __init__(self, config: bt.Config):
        bt.logging.info("Initializing Validator...")

        self.wallet = bt.wallet(config=config)
        self.subtensor = bt.subtensor(config=config)
        self.dendrite = bt.dendrite(wallet=self.wallet)
        self.netuid = config.netuid
        self.ping_frequency = config.ping_frequency or 600
        self.eval_frequency = config.eval_frequency or 600
        self.last_eval_time = 0
        self.no_zero_weights = config.no_zero_weights or False
        os.makedirs(merit_config.EPOCH_RESULTS_DIR, exist_ok=True)
        self.latest_ping_success = {}
        self.valid_miners = set()
        self.ping_complete = asyncio.Event()
        self.ping_task = None
        self.first_ping_done = False
        self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
        self.state = self._load_state()
        self.health = self._load_health()
        self.all_metagraphs_info = self._fetch_all_metagraphs_info()
        self.eval_rounds = 0
        self.ping_retry_attempts = merit_config.PING_RETRY_ATTEMPTS
        self.ping_retry_delay = merit_config.PING_RETRY_DELAY
        self.latest_ping_times = {}

    async def cleanup(self):
        """
        Gracefully close all async resources (e.g., aiohttp sessions).
        """
        bt.logging.info("Validator cleanup: Closing Dendrite session.")
        try:
            await self.dendrite.aclose_session()
        except Exception as e:
            bt.logging.error(f"Error closing dendrite session: {e}")

    def _fetch_all_metagraphs_info(self):
        try:
            infos = self.subtensor.get_all_metagraphs_info()
            bt.logging.success(f"Fetched {len(infos)} metagraphs info.")
            return infos
        except Exception as e:
            bt.logging.warning(f"Failed to fetch all metagraphs info: {e}")
            return []

    def _load_state(self):
        if os.path.isfile(merit_config.STATE_FILE):
            with open(merit_config.STATE_FILE, "r") as f:
                return json.load(f)
        return {}

    def _save_state(self):
        with open(merit_config.STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=4)

    def _clear_state(self):
        if os.path.isfile(merit_config.STATE_FILE):
            os.remove(merit_config.STATE_FILE)

    def _load_health(self):
        if os.path.isfile(merit_config.HEALTH_FILE):
            with open(merit_config.HEALTH_FILE, "r") as f:
                return json.load(f)
        return {}

    def _save_health(self):
        with open(merit_config.HEALTH_FILE, "w") as f:
            json.dump(self.health, f, indent=4)

    def _prune_epoch_results(self):
        if not os.path.isdir(merit_config.EPOCH_RESULTS_DIR):
            bt.logging.warning(f"Epoch results directory {merit_config.EPOCH_RESULTS_DIR} not found. Skipping prune.")
            return
        files = sorted([
            f for f in os.listdir(merit_config.EPOCH_RESULTS_DIR) if f.startswith("epoch_")
        ])
        for old_file in files[:-merit_config.MAX_EPOCH_FILES]:
            os.remove(os.path.join(merit_config.EPOCH_RESULTS_DIR, old_file))

    def is_valid_public_ipv4(self, ip: str) -> bool:
        try:
            parsed_ip = ipaddress.IPv4Address(ip)
            return parsed_ip.is_global
        except ipaddress.AddressValueError:
            return False

    def _should_skip_neuron(self, neuron) -> bool:
        try:
            return neuron.dividends > 0 or neuron.validator_trust > 0
        except Exception:
            return False

    async def _is_port_open(self, ip: str, port: int) -> bool:
        try:
            await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=4.0)
            return True
        except Exception:
            return False

    async def ping_miner(self, neuron) -> bool:
        axon = neuron.axon_info
        ip = axon.ip
        port = axon.port

        if not self.is_valid_public_ipv4(ip) or port == 0:
            bt.logging.debug(f"Skipping invalid IP/port for {neuron.hotkey}: {ip}:{port}")
            return False

        for attempt in range(self.ping_retry_attempts):
            if await self._is_port_open(ip, port):
                break
            if attempt < self.ping_retry_attempts - 1:
                await asyncio.sleep(self.ping_retry_delay)
        else:
            bt.logging.debug(f"Port closed after {self.ping_retry_attempts} attempts for {neuron.hotkey}")
            return False

        try:
            request = PingSynapse(hotkey=neuron.hotkey)
            response = await self.dendrite.forward(axon, request, timeout=merit_config.PING_TIMEOUT)

            if not isinstance(response, PingSynapse) or not response.token:
                bt.logging.debug(f"Invalid response or missing token from {neuron.hotkey}")
                return False

            hashed = hashlib.sha256(neuron.hotkey.encode('utf-8')).digest()
            base32_secret = base64.b32encode(hashed).decode('utf-8').strip('=')
            totp = pyotp.TOTP(base32_secret)

            if not totp.verify(response.token, valid_window=1):
                bt.logging.debug(f"TOTP failed for {neuron.hotkey}")
                return False

            self.latest_ping_times[neuron.hotkey] = time.time()
            bt.logging.debug(f"Ping success for {neuron.hotkey}")
            return True


        except Exception as e:
            bt.logging.warning(f"Ping exception for {neuron.hotkey}: {e}")
            return False

    async def _background_pinger(self):
        while True:
            try:
                self.ping_complete.clear()

                self.metagraph.sync(subtensor=self.subtensor)
                self.all_metagraphs_info = self._fetch_all_metagraphs_info()
                bt.logging.debug("Starting background ping round...")

                ping_targets = [
                    neuron for neuron in self.metagraph.neurons
                    if not self._should_skip_neuron(neuron)
                ]

                results = await asyncio.gather(
                    *(self.ping_miner(neuron) for neuron in ping_targets),
                    return_exceptions=True
                )

                self.valid_miners.clear()
                for neuron, result in zip(ping_targets, results):
                    if isinstance(result, Exception):
                        bt.logging.warning(f"Exception pinging {neuron.hotkey}: {result}")
                        success = False
                    else:
                        success = result

                    self.latest_ping_success[neuron.hotkey] = success
                    if success:
                        self.valid_miners.add(neuron.hotkey)

                total_targets = len(ping_targets)
                failed = total_targets - len(self.valid_miners)
                reachable_count = len(self.valid_miners)
                bt.logging.info(
                    f"{len(self.valid_miners)} reachable, {failed} unreachable out of {total_targets} ping targets.")
                bt.logging.success(f"Ping round complete. {reachable_count} miners reachable.")
                self.first_ping_done = True
                self.ping_complete.set()

            except Exception as e:
                bt.logging.error(f"Background pinger error: {e}")

            await asyncio.sleep(self.ping_frequency)

    def _evaluate_miners(self):
        bt.logging.debug("Evaluating miners...")
        self.state = {}
        evaluated_count = 0

        expected_subnets = [
            info for info in self.all_metagraphs_info
            if info.netuid not in (0, self.netuid)
        ]
        num_expected_subnets = len(expected_subnets)

        for neuron in self.metagraph.neurons:
            if self._should_skip_neuron(neuron):
                continue

            hotkey = neuron.hotkey
            axon = neuron.axon_info

            if not self.is_valid_public_ipv4(axon.ip) or axon.port == 0:
                bt.logging.debug(f"Skipping {hotkey}: Invalid axon IP or port ({axon.ip}:{axon.port})")
                self.state[hotkey] = 0.0
                continue

            if hotkey not in self.valid_miners:
                bt.logging.debug(f"Miner {hotkey} was not pinged successfully or skipped. Assigning BMPs=0.0")
                self.state[hotkey] = 0.0
                continue

            incentives_with_netuid = []
            for info in expected_subnets:
                hotkey_to_incentive = dict(zip(info.hotkeys, info.incentives))
                incentive = hotkey_to_incentive.get(hotkey, 0.0)
                incentives_with_netuid.append((info.netuid, incentive))

            incentives = [val for _, val in incentives_with_netuid]

            avg_incentive = sum(incentives) / num_expected_subnets if num_expected_subnets > 0 else 0.0
            bmps = avg_incentive * 100000
            self.state[hotkey] = bmps

            bt.logging.debug(
                f"Miner {hotkey}: Subnet Incentives = {incentives_with_netuid}, "
                f"Avg = {avg_incentive:.6f}, BMPs = {bmps:.2f}"
            )

            evaluated_count += 1

        self._save_state()
        total_neurons = len([n for n in self.metagraph.neurons if not self._should_skip_neuron(n)])
        skipped = total_neurons - evaluated_count
        bt.logging.info(f"Evaluated {evaluated_count} miners (others set to 0.0 = {skipped}).")
        self.eval_rounds += 1
        bt.logging.info(f"Evaluation round #{self.eval_rounds} complete.")

    def _calculate_normalized_weights(self, uids, scores, burner_uid=0, burner_weight=0.75):
        """
        Calculates normalized weights using an S-curve incentive model.
        UID 0 always receives `burner_weight` (default 75%).
        Only miners with score > 0.0 share the remaining 25%.
        """

        # Filter out burner UID and zero-score miners
        valid_miners = [(uid, score) for uid, score in zip(uids, scores) if uid != burner_uid and score > 0.0]

        if not valid_miners:
            bt.logging.warning("No valid scoring miners found. Assigning full weight to burner UID.")
            return [burner_weight if uid == burner_uid else 0.0 for uid in uids]

        # Rank valid miners
        ranked_miners = sorted(valid_miners, key=lambda x: x[1], reverse=True)

        # Apply S-curve reward formula
        incentive_rewards = []
        for rank, (uid, _) in enumerate(ranked_miners, start=1):
            reward = (-1.038e-7 * (rank ** 3)) + (6.214e-5 * (rank ** 2)) - (0.0129 * rank) - 0.0118 + 1
            incentive_rewards.append(max(reward, 0))

        total_incentive = sum(incentive_rewards)
        if total_incentive <= 0:
            bt.logging.warning("Total incentive is non-positive. Distributing 25% equally among valid miners.")
            even_weight = (1.0 - burner_weight) / len(valid_miners)
            miner_weights = {uid: even_weight for uid, _ in ranked_miners}
        else:
            miner_weights = {
                uid: (reward / total_incentive) * (1.0 - burner_weight)
                for (uid, _), reward in zip(ranked_miners, incentive_rewards)
            }

        # Assemble full weight vector
        final_weights = []
        for uid in uids:
            if uid == burner_uid:
                final_weights.append(burner_weight)
            else:
                final_weights.append(miner_weights.get(uid, 0.0))

        return final_weights

    async def run(self):
        bt.logging.info("Validator running...")

        if self.ping_task is None:
            self.ping_task = asyncio.create_task(self._background_pinger())

        try:
            while True:
                current_block = self.subtensor.get_current_block()
                try:
                    my_uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
                except ValueError:
                    bt.logging.error("Validator hotkey not found in metagraph. Skipping weight set.")
                    await asyncio.sleep(30)
                    continue
                blocks_since_update = self.subtensor.blocks_since_last_update(netuid=self.netuid, uid=my_uid)

                bt.logging.debug(
                    f"My UID: {my_uid}, blocks since last weights set: {blocks_since_update}, TEMPO: {merit_config.TEMPO}")

                if not self.first_ping_done:
                    bt.logging.debug("Waiting for first ping round to complete...")
                    await asyncio.sleep(3)
                    continue

                now = time.time()
                if now - self.last_eval_time >= self.eval_frequency:
                    await asyncio.shield(self.ping_complete.wait())
                    self._evaluate_miners()
                    self.last_eval_time = now

                if blocks_since_update >= (merit_config.TEMPO - 2):
                    bt.logging.info("Enough blocks passed. Setting weights now...")

                    uids, scores = [], []
                    for neuron in self.metagraph.neurons:
                        if self._should_skip_neuron(neuron):
                            continue
                        uids.append(neuron.uid)
                        score = self.state.get(neuron.hotkey, 0.0)
                        scores.append(score)

                    burner_uid = 0
                    if burner_uid not in uids:
                        bt.logging.debug(f"Inserting burner UID {burner_uid} for burn allocation.")
                        uids.insert(0, burner_uid)
                        scores.insert(0, 0.0)

                    total_bmps = sum(score for uid, score in zip(uids, scores) if uid != burner_uid)

                    if total_bmps == 0 and self.no_zero_weights and len(scores) > 0:
                        bt.logging.warning("All scores are zero, but --no_zero_weights is set. "
                                           "Assigning 75% to burner UID and 25% evenly among others.")
                        eligible_count = len([uid for uid in uids if uid != burner_uid])
                        distributed_weight = (1.0 - 0.75) / eligible_count if eligible_count > 0 else 0.0
                        normalized_weights = [0.75 if uid == burner_uid else distributed_weight for uid in uids]
                    elif total_bmps > 0:
                        normalized_weights = self._calculate_normalized_weights(uids, scores, burner_uid=burner_uid,
                                                                                burner_weight=0.75)
                    else:
                        normalized_weights = []

                    if normalized_weights:
                        bt.logging.info(f"Setting weights: total_bmps = {total_bmps:.4f}")

                        bt.logging.debug("Final normalized weights (uid: weight, hotkey):")
                        for uid, score in zip(uids, normalized_weights):
                            hotkey = self.metagraph.hotkeys[uid]
                            bt.logging.debug(f"  UID {uid:4d} | Weight = {score:.6f} | Hotkey = {hotkey}")

                        weight_sum = sum(normalized_weights)
                        if not (0.999 <= weight_sum <= 1.001):
                            bt.logging.warning(f"⚠️ Normalized weights sum to {weight_sum:.6f}, not ≈1.0")

                        self.subtensor.set_weights(
                            wallet=self.wallet,
                            netuid=self.netuid,
                            uids=uids,
                            weights=normalized_weights,
                            version_key=self.metagraph.hparams.weights_version,
                            wait_for_inclusion=True,
                        )
                        bt.logging.success(
                            f"Weights set successfully at block {current_block} (Eval round #{self.eval_rounds}).")

                        block = self.subtensor.get_current_block()
                        path = os.path.join(merit_config.EPOCH_RESULTS_DIR, f"epoch_{block}.json")
                        epoch_summary = {}

                        for neuron in self.metagraph.neurons:
                            if self._should_skip_neuron(neuron):
                                continue

                            hotkey = neuron.hotkey
                            uid = neuron.uid
                            score = self.state.get(hotkey, 0.0)
                            weight = next((w for u, w in zip(uids, normalized_weights) if u == uid), 0.0)

                            subnet_incentives = {}
                            for info in self.all_metagraphs_info:
                                if info.netuid in (0, self.netuid):
                                    continue
                                if hotkey in info.hotkeys:
                                    index = info.hotkeys.index(hotkey)
                                    subnet_incentives[info.netuid] = round(info.incentives[index], 6)

                            ping_success = self.latest_ping_success.get(hotkey, False)
                            last_ping_ts = self.latest_ping_times.get(hotkey, 0.0)

                            epoch_summary[hotkey] = {
                                "uid": uid,
                                "weight": round(weight, 6),
                                "bmps": round(score, 6),
                                "subnet_incentives": subnet_incentives,
                                "ping_success": ping_success,
                                "last_ping_timestamp": last_ping_ts,
                                "timestamp": time.time()
                            }

                        with open(path, "w") as f:
                            json.dump(epoch_summary, f, indent=4)
                    else:
                        bt.logging.warning("All scores are zero, skipping setting weights.")

                    self._clear_state()
                    self.state = {}
                    self._prune_epoch_results()
                else:
                    bt.logging.debug(f"Not enough blocks passed yet ({blocks_since_update}). Waiting...")

                await asyncio.sleep(12)

        except asyncio.CancelledError:
            bt.logging.warning("Validator shutdown requested.")
        finally:
            if self.ping_task:
                self.ping_task.cancel()
                try:
                    await self.ping_task
                except asyncio.CancelledError:
                    bt.logging.debug("Ping task cancelled cleanly.")

            start = time.time()
            await self.cleanup()
            bt.logging.info(f"Validator shutdown complete in {time.time() - start:.2f}s.")
