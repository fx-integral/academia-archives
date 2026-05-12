import re
import time

import bittensor as bt
from natix.protocol import prepare_synapse
from natix.utils.wandb_utils import log_to_wandb
from natix.validator.api_client import statistics_assign_task, statistics_report_task_batch
from natix.validator.challenge import determine_challenge_type, fetch_api_challenge
from natix.validator.scoring import get_rewards
from natix.validator.utils import fix_ip_format


async def forward(self):
    # Subnet is halted: skip all miner queries and scoring.
    bt.logging.info("Subnet halted: skipping challenge forward pass.")
    return

    challenge_metadata = {}
    label, modality, source_model_task, cache, source = determine_challenge_type(
        self.media_cache, self.synthetic_media_cache
    )
    challenge_metadata.update({"label": label, "modality": modality, "source_model_task": source_model_task, "source": source})

    bt.logging.info(f"Sampling {source} {modality} challenge (label={label})")

    if modality != "image":
        bt.logging.error(f"Unexpected modality: {modality}")
        return
    elif source == "api":
        challenge = await fetch_api_challenge(self, label)
        if challenge is not None:
            label = challenge["label"]
    else:
        challenge = cache.sample(label)

    if challenge is None:
        bt.logging.warning("Challenge unavailable. Skipping.")
        return

    challenge_metadata.update({k: v for k, v in challenge.items() if re.match(r"^(?!image$|video$|videos$|video_\d+$).+", k)})
    input_data = challenge[modality]

    miner_uids = self.uid_deck.next_k(
        k=self.config.neuron.sample_size,
        metagraph=self.metagraph,
        vpermit_tao_limit=self.config.neuron.vpermit_tao_limit,
        exclude=None,
    )
    axons = [fix_ip_format(self.metagraph.axons[uid]) for uid in miner_uids]
    challenge_metadata["miner_uids"] = miner_uids
    challenge_metadata["miner_hotkeys"] = [axon.hotkey for axon in axons]

    synapse = prepare_synapse(input_data, modality=modality)

    try:
        statistics_response = statistics_assign_task(self, miner_uid_list=miner_uids, scoring_method=0, category=0, label=int(label), image=synapse.image, task_id=challenge.get("task_id"))
    except Exception as e:
        bt.logging.error(f"Failed to report task assignment to statistics: {e}")

    bt.logging.info(f"Sending {modality} challenge to {len(miner_uids)} miners")
    start = time.time()
    responses = await self.dendrite(axons=axons, synapse=synapse, deserialize=False, timeout=9)
    predictions = [x.prediction for x in responses]
    bt.logging.debug(f"Predictions of {source} challenge: {predictions}")

    try:
        statistics_report_task_batch(self, miner_uid_list=miner_uids, predictions=predictions, task_id=statistics_response["id"])
    except Exception as e:
        bt.logging.error(f"Failed to report task responses to statistics: {e}")

    bt.logging.info(f"Responses received in {time.time() - start}s")
    bt.logging.success(f"Roadwork {modality} challenge complete!")

    rewards, metrics = get_rewards(
        label=label,
        responses=predictions,
        uids=miner_uids,
        axons=axons,
        performance_trackers=self.performance_trackers,
    )
    self.update_scores(rewards, miner_uids)

    for metric_name in list(metrics[0][modality].keys()):
        challenge_metadata[f"miner_{modality}_{metric_name}"] = [m[modality][metric_name] for m in metrics]

    challenge_metadata.update({"predictions": predictions, "rewards": rewards.tolist(), "scores": list(self.scores)})

    for uid, pred, reward in zip(miner_uids, predictions, rewards):
        if pred != -1:
            bt.logging.success(f"UID: {uid} | Prediction: {pred} | Reward: {reward}")

    if not self.config.wandb.off:
        log_to_wandb(challenge_metadata=challenge_metadata, responses=responses, rewards=rewards, metrics=metrics, scores=self.scores, axons=axons)

    self.save_miner_history()
    if cache is not None:
        cache._prune_extracted_cache()
