import asyncio
import threading
import time
from io import BytesIO

import bittensor as bt
import httpx
from PIL import Image

from natix.protocol import prepare_synapse
from natix.validator.api_client import build_auth_headers
from natix.validator.api_client import statistics_assign_task, statistics_report_task_batch
from natix.validator.utils import fix_ip_format
from natix.validator.config import MAX_TASKS_PER_DAY, ORGANIC_TASK_RATIO

from natix.validator.scoring import get_rewards

_SECONDS_PER_DAY = 86_400
# One poll sends one scoring_method:1 task.
_ORGANIC_POLL_INTERVAL = max(30, int(_SECONDS_PER_DAY / (MAX_TASKS_PER_DAY * ORGANIC_TASK_RATIO)))


class ValidatorProxy:
    def __init__(self, validator):
        self.validator = validator
        self.poll_interval = _ORGANIC_POLL_INTERVAL
        threading.Thread(target=self._run_poll_loop, daemon=True).start()

    def _run_poll_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        dendrite = bt.dendrite(wallet=self.validator.wallet)
        loop.run_until_complete(self._poll_loop(dendrite))

    async def _poll_loop(self, dendrite):
        while True:
            try:
                await self._poll_and_distribute(dendrite)
            except Exception as e:
                bt.logging.error(f"[ORGANIC] Consensus poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _poll_and_distribute(self, dendrite):
        api_url = self.validator.config.proxy.proxy_client_url
        print("api_url", api_url)
        wallet = self.validator.wallet

        # Request a consensus task from the API
        try:
            headers = build_auth_headers(wallet)
            body = {"scoring_method": 1, "category": 0}
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                response = await client.post(
                    f"{api_url}/tasks/request",
                    headers=headers,
                    json=body,
                )
            if response.status_code == 404:
                bt.logging.info("[ORGANIC] No consensus tasks available")
                return
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", self.poll_interval)
                bt.logging.warning(f"[ORGANIC] Rate limited, retry after {retry_after}s")
                await asyncio.sleep(int(retry_after))
                return
            response.raise_for_status()
            task = response.json()
        except httpx.HTTPStatusError as e:
            bt.logging.warning(f"[ORGANIC] Task request failed: {e.response.status_code}")
            return
        except Exception as e:
            bt.logging.error(f"[ORGANIC] Task request error: {e}")
            return

        task_id = task["task_id"]
        s3_url = task["s3_url"]
        category = task["category"]
        bt.logging.info(f"[ORGANIC] Got consensus task {task_id}, category={category}")

        # Download image from presigned S3 URL
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                img_response = await client.get(s3_url)
                img_response.raise_for_status()
            image = Image.open(BytesIO(img_response.content)).convert("RGB")
            print("image len: ", len(image))
        except Exception as e:
            bt.logging.error(f"[ORGANIC] Failed to download task image: {e}")
            return

        # Sample miner UIDs
        miner_uids = self.validator.organic_uid_deck.next_k(
            k=self.validator.config.neuron.sample_size,
            metagraph=self.validator.metagraph,
            vpermit_tao_limit=self.validator.config.neuron.vpermit_tao_limit,
            exclude=None,
        )
        if not miner_uids:
            bt.logging.warning("[ORGANIC] No eligible miners available")
            return

        axons = [fix_ip_format(self.validator.metagraph.axons[uid]) for uid in miner_uids]
        synapse = prepare_synapse(image, modality="image")

        # Report task assignment to statistics
        statistics_response = statistics_assign_task(
            self.validator,
            miner_uid_list=miner_uids,
            scoring_method=1,
            category=category,
            label=0,
            image=synapse.image,
            task_id=task_id,
        )

        # Query miners
        bt.logging.info(f"[ORGANIC] Sending consensus task to {len(miner_uids)} miners")
        start = time.time()
        responses = await dendrite(
            axons=axons, synapse=synapse, deserialize=False, timeout=9
        )
        predictions = [x.prediction for x in responses]
        bt.logging.info(f"[ORGANIC] Responses received in {time.time() - start:.1f}s")

        # Determine consensus label from majority vote of valid predictions
        valid_preds = [p for p in predictions if p != -1]
        if not valid_preds:
            bt.logging.warning("[ORGANIC] No valid predictions received")
            return
        consensus_label = round(sum(valid_preds) / len(valid_preds))

        # Report miner responses to statistics
        if statistics_response:
            statistics_report_task_batch(
                self.validator,
                miner_uid_list=miner_uids,
                predictions=predictions,
                task_id=statistics_response["id"],
            )

        # Score miners and update validator state
        rewards, _ = get_rewards(
            label=consensus_label,
            responses=predictions,
            uids=miner_uids,
            axons=axons,
            performance_trackers=self.validator.performance_trackers,
        )
        self.validator.update_scores(rewards, miner_uids)

        bt.logging.success(
            f"[ORGANIC] Task {task_id} complete | consensus_label={consensus_label} | "
            f"{len(valid_preds)}/{len(miner_uids)} valid responses"
        )
        self.validator.save_miner_history()
