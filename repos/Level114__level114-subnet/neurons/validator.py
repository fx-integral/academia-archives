# The MIT License (MIT)
# Copyright © 2025 Level114 Team

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import asyncio
import time
import bittensor as bt
from level114.utils.uids import sequential_select_untrusted

from level114.base.validator import BaseValidatorNeuron
from level114.validator.runner import Level114ValidatorRunner
from level114.validator.mechanisms import MinecraftMechanism, TclMechanism

MIN_VALIDATION_INTERVAL = 24 * 60  # seconds (24 minutes)


class Validator(BaseValidatorNeuron):
    """
    Level114 validator neuron class. This validator queries nodes for their performance metrics
    and uses those metrics to set weights based on node performance evaluation.
    
    The validator queries nodes that have registered with the collector-center-main service
    and evaluates their reported metrics to determine appropriate weight distributions.
    """

    def __init__(self, config=None):
        super(Validator, self).__init__(config=config)

        bt.logging.info("load_state()")
        self.load_state()
        
        # Initialize Level114 scoring system
        bt.logging.info("Initializing Level114 scoring system...")
        try:
            # Initialize the comprehensive validator runner
            self.scoring_runner = Level114ValidatorRunner(
                config=self.config,
                subtensor=self.subtensor,
                metagraph=self.metagraph,
                wallet=self.wallet,
                collector_api=self.collector_api,
            )
            
            bt.logging.success("✅ Level114 scoring system initialized successfully")
            init_status = self.scoring_runner.get_status()
            mechanisms = init_status.get('mechanisms', {}) or {}
            mechanism_descriptions = ", ".join(
                f"{mid}:{info.get('mechanism_name')}"
                for mid, info in sorted(mechanisms.items())
            ) or "none"
            bt.logging.info(f"⚙️  Validator mechanisms: {mechanism_descriptions}")
            bt.logging.info(f"⚖️  Weight update interval: {getattr(self.config.validator, 'weight_update_interval', 300)}s")
            
        except Exception as e:
            bt.logging.error(f"❌ Failed to initialize scoring system: {e}")
            raise

    async def validate(self):
        """
        Main validation step using Level114 comprehensive scoring system
        
        This replaces the basic validation with our advanced scoring that:
        1. Fetches all server reports from collector API
        2. Verifies report integrity (hash/signature validation)
        3. Calculates comprehensive scores (infrastructure, participation, reliability)
        4. Updates Bittensor weights based on server performance
        5. Pulls historical context from the collector
        """
        try:
            # Check if enough time has passed since last validation
            configured_interval = getattr(
                self.config.validator, 'validation_interval', MIN_VALIDATION_INTERVAL
            )
            validation_interval = max(configured_interval, MIN_VALIDATION_INTERVAL)
            current_time = time.time()
            
            if not hasattr(self, 'last_validation_time'):
                self.last_validation_time = 0
            
            if (
                validation_interval > configured_interval
                and not getattr(self, '_warned_validation_interval', False)
            ):
                bt.logging.warning(
                    f"Validation interval increased to {validation_interval}s (minimum enforced)"
                )
                self._warned_validation_interval = True
            
            if current_time - self.last_validation_time < validation_interval:
                # Not time for validation yet, just wait
                await asyncio.sleep(1)
                return
            
            bt.logging.info("🔄 Starting Level114 validation cycle...")
            
            # Run comprehensive scoring cycle
            cycle_stats = await self.scoring_runner.run_scoring_cycle()
            mechanisms = cycle_stats.get('mechanisms', {}) or {}
            minecraft_stats = mechanisms.get(MinecraftMechanism.mechanism_id, {}) or {}
            cursed_stats = mechanisms.get(TclMechanism.mechanism_id, {}) or {}
            weights_map = cycle_stats.get('weights_updated', {}) or {}
            minecraft_weights_updated = weights_map.get(MinecraftMechanism.mechanism_id)

            # Update last validation time
            self.last_validation_time = current_time

            # Log detailed results
            bt.logging.info(
                (
                    "✅ Validation cycle {cycle} complete | Minecraft servers: {mc_processed} processed, "
                    "{mc_scores} scores (weights updated={weights_updated}) | TCL metrics: {tcl_hotkeys} hotkeys, "
                    "{tcl_metrics} collected | errors={errors} | cycle time={duration:.1f}s"
                ).format(
                    cycle=cycle_stats.get('cycle_id'),
                    mc_processed=minecraft_stats.get('servers_processed', 0),
                    mc_scores=minecraft_stats.get('scores_updated', 0),
                    weights_updated=minecraft_weights_updated,
                    tcl_hotkeys=cursed_stats.get('hotkeys_processed', 0),
                    tcl_metrics=cursed_stats.get('metrics_collected', 0),
                    errors=cycle_stats.get('errors', 0),
                    duration=cycle_stats.get('total_time', 0.0),
                )
            )

            # Update traditional scores for compatibility with base class
            # This ensures existing monitoring and state saving still works
            if minecraft_stats.get('scores_updated', 0) > 0:
                self._update_legacy_scores()
            
            # Status summary every 10 cycles
            if self.scoring_runner.cycle_count % 10 == 0:
                self._log_validator_status()
            
        except Exception as e:
            bt.logging.error(f"❌ Error in validation cycle: {e}")
            bt.logging.error(f"❌ Error details: {type(e).__name__}: {str(e)}")
            
            # Fall back to basic validation to avoid complete failure
            try:
                bt.logging.warning("🔧 Attempting fallback validation...")
                await self._basic_fallback_validation()
            except Exception as fallback_error:
                bt.logging.error(f"❌ Fallback validation also failed: {fallback_error}")
                # Wait a bit longer if both systems fail
                await asyncio.sleep(30)
    
    def _update_legacy_scores(self):
        """
        Update legacy scoring system for compatibility with base validator class
        
        This syncs our advanced scoring results with the traditional score tracking
        so existing state saving, monitoring, and UI still work correctly.
        """
        try:
            # Get current scores from our scoring system
            hotkey_to_uid = {axon.hotkey: uid for uid, axon in enumerate(self.metagraph.axons)}
            
            # Initialize score updates
            score_updates = {}
            
            # Get scores from cached collector data for each active server
            for hotkey in self.metagraph.hotkeys:
                if hotkey in hotkey_to_uid:
                    uid = hotkey_to_uid[hotkey]
                    
                    # Try to get server ID and cached score for this hotkey
                    server_id = self.scoring_runner.get_server_id_for_hotkey(hotkey)
                    if not server_id:
                        continue

                    score_entry = self.scoring_runner.get_cached_score(server_id)
                    if not score_entry:
                        continue

                    # Convert our 0-1000 score to 0-1 range for legacy system
                    normalized_score = score_entry.score / 1000.0
                    score_updates[uid] = normalized_score
            
            # Update scores if we have any
            if score_updates:
                for uid, score in score_updates.items():
                    if uid < len(self.scores):
                        self.scores[uid] = score
                
                bt.logging.debug(f"Updated legacy scores for {len(score_updates)} miners")
            
        except Exception as e:
            bt.logging.error(f"Error updating legacy scores: {e}")
    
    def _log_validator_status(self):
        """Log comprehensive validator status summary"""
        try:
            status = self.scoring_runner.get_status()
            
            bt.logging.info("=" * 60)
            bt.logging.info("📊 LEVEL114 VALIDATOR STATUS SUMMARY")
            bt.logging.info("=" * 60)
            mechanisms_status = status.get('mechanisms', {}) or {}
            mechanism_overview = ", ".join(
                f"{mid}:{info.get('mechanism_name')}"
                for mid, info in sorted(mechanisms_status.items())
            ) or 'n/a'
            bt.logging.info(f"⚙️  Mechanisms active: {mechanism_overview}")
            bt.logging.info(f"🔄 Global cycles completed: {status.get('cycle_count', 0)}")

            for mid, info in sorted(mechanisms_status.items()):
                bt.logging.info(
                    f"   • Mechanism {mid} ({info.get('mechanism_name')}): cycles={info.get('cycle_count', 0)}"
                )
                if mid == MinecraftMechanism.mechanism_id:
                    bt.logging.info(
                        f"     ↳ Cached scores: {info.get('cached_scores')}, mappings: {info.get('cached_mappings')}"
                    )
                if mid == TclMechanism.mechanism_id:
                    bt.logging.info(
                        f"     ↳ Cached TCL metrics: {info.get('metrics_cached')}"
                    )

            last_weights_update = status.get('last_weights_update')
            if last_weights_update:
                readable = time.ctime(last_weights_update)
            else:
                readable = 'Never'
            bt.logging.info(f"⚖️  Last weights update: {readable}")

            cached_scores = status.get('cached_scores')
            if cached_scores is not None:
                bt.logging.info(f"🗂️  Cached scores: {cached_scores}")
            metrics_cached = status.get('metrics_cached')
            if metrics_cached is not None:
                bt.logging.info(f"📊 Cached TCL metrics: {metrics_cached}")

            cached_mappings = status.get('cached_mappings')
            if cached_mappings is not None:
                bt.logging.info(f"📇 Cached mappings: {cached_mappings}")

            replay_active = status.get('replay_protection_active')
            if replay_active is not None:
                bt.logging.info(f"🔒 Replay protection: {'Active' if replay_active else 'Inactive'}")

            # Network info
            bt.logging.info(f"🌐 Network: {self.config.subtensor.network}")
            config_snapshot = status.get('config', {}) or {}
            bt.logging.info(f"🔢 Subnet: {config_snapshot.get('netuid', 'n/a')}")
            bt.logging.info(f"👥 Metagraph size: {self.metagraph.n}")

            # Weight timing
            weight_interval = config_snapshot.get('weight_update_interval')
            next_update = status.get('next_weight_update')
            if next_update is None and last_weights_update and weight_interval:
                next_update = last_weights_update + weight_interval
            if next_update is not None:
                time_to_next = max(0, next_update - time.time())
                bt.logging.info(f"⏰ Next weight update: {time_to_next:.0f}s")
            retry_interval = config_snapshot.get('weight_retry_interval')
            if retry_interval is not None:
                bt.logging.info(f"🔁 Weight retry interval: {retry_interval}s")

            bt.logging.info("=" * 60)

        except Exception as e:
            bt.logging.error(f"Error logging validator status: {e}")
    
    async def _basic_fallback_validation(self):
        """
        Basic fallback validation in case our comprehensive system fails
        
        This provides minimal functionality to keep the validator running
        while issues with the scoring system are resolved.
        """
        bt.logging.warning("⚠️  Using basic fallback validation")
        
        try:
            # Basic sampling like the original validator
            sample_size = min(getattr(self.config.neuron, 'sample_size', 10), len(self.metagraph.hotkeys))
            start_index = getattr(self, 'selection_index', 0)
            selected_uids, next_index = sequential_select_untrusted(self.metagraph, sample_size, start_index)
            self.selection_index = next_index
            
            selected_hotkeys = [self.metagraph.hotkeys[uid] for uid in selected_uids]
            bt.logging.info(f"🔍 Fallback validation: checking {len(selected_hotkeys)} hotkeys")
            
            # Try to fetch some basic data
            if selected_hotkeys:
                status, servers = self.collector_api.get_validator_server_ids(selected_hotkeys)
                if 200 <= status < 300:
                    bt.logging.info(f"✅ Collector API accessible: {len(servers)} servers found")
                else:
                    bt.logging.warning(f"⚠️  Collector API issue: status {status}")
            
        except Exception as e:
            bt.logging.error(f"❌ Error in fallback validation: {e}")


if __name__ == "__main__":
    try:
        Validator().run()
    except KeyboardInterrupt:
        pass
