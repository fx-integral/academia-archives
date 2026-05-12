import asyncio
from datetime import UTC, datetime

from subnet_validator.models import CouponResponse
from subnet_validator.services.coupon_service import CouponService
from subnet_validator.services.validator_sync_offset_service import (
    ValidatorSyncOffsetService,
)
from subnet_validator.services.metagraph_service import MetagraphService
from subnet_validator.settings import (
    Settings,
)
from fiber.chain import (
    chain_utils,
)
from subnet_validator import (
    dependencies,
)
from fiber.logging_utils import (
    get_logger,
)
from fiber.chain.models import (
    Node,
)
import httpx
from typing import List
from pydantic import TypeAdapter


async def sync_coupons(is_first_sync: bool = False, context=None, **services):
    logger = get_logger(__name__)

    # Extract services from kwargs
    coupon_service = services["coupon_service"]
    validator_sync_offset_service = services["validator_sync_offset_service"]

    # Use context.get_settings() if available, otherwise fallback to direct call
    if context:
        settings = context.get_settings()
    else:
        from . import dependencies

        settings = dependencies.get_settings()

    logger.info("Syncing coupons")

    # Get metagraph from context or factory config
    if context:
        metagraph = context.metagraph
    else:
        # Fallback to factory config
        from . import dependencies

        factory_config = dependencies.get_factory_config()
        metagraph = factory_config.metagraph

    # Get validator nodes from metagraph
    validator_nodes = metagraph.get_validator_nodes()

    keypair = chain_utils.load_hotkey_keypair(
        wallet_name=settings.wallet_name,
        hotkey_name=settings.hotkey_name,
    )
    current_validator_node = next(
        (
            node
            for node in validator_nodes
            if node.hotkey == keypair.ss58_address
        ),
        None,
    )
    if current_validator_node:
        validator_nodes.remove(current_validator_node)
    if not validator_nodes:
        logger.warning("No validator nodes found")
        return

    # Initialize sync progress if this is the first run (explicit)
    if is_first_sync:
        try:
            progress = {
                "started_at": datetime.now(UTC).isoformat(),
                "total_validators": len(validator_nodes),
                "validators": {
                    node.hotkey: {
                        "ip": getattr(node, "ip", None),
                        "port": getattr(node, "port", None),
                        "status": "pending",
                        "last_synced": None,
                    }
                    for node in validator_nodes
                },
            }
            coupon_service.dynamic_config_service.set_sync_progress(progress)
            logger.info(
                f"First-time coupon sync detected. Initialized progress for {len(validator_nodes)} validators"
            )
        except Exception as e:
            logger.error(f"Failed to initialize sync progress: {e}")

    await _sync_coupons_for_validators(
        settings,
        validator_nodes,
        coupon_service,
        validator_sync_offset_service,
        logger,
        is_first_sync,
    )
    logger.info(
        f"Finished syncing coupons for {len(validator_nodes)} validators."
    )


async def _sync_coupons_for_validators(
    settings: Settings,
    validator_nodes: list[Node],
    coupon_service: CouponService,
    validator_sync_offset_service: ValidatorSyncOffsetService,
    logger,
    is_first_sync: bool,
):
    dynamic_config_service = coupon_service.dynamic_config_service

    processed_total_synced = 0
    errors_total = 0
    empty_total = 0
    responded_total = 0
    validators_with_coupons_total = 0
    coupons_fetched_total = 0

    async def fetch_and_store(node: Node):
        nonlocal responded_total, coupons_fetched_total, empty_total
        nonlocal validators_with_coupons_total, processed_total_synced, errors_total
        hotkey = getattr(node, "hotkey", None)
        ip = getattr(node, "ip", None)
        port = getattr(node, "port", None)
        last_synced = (
            validator_sync_offset_service.get_last_coupon_action_date(hotkey)
        )
        if is_first_sync:
            try:
                progress = dynamic_config_service.get_sync_progress() or {}
                validators = progress.get("validators", {})
                node_progress = validators.get(hotkey, {})
                node_progress.update(
                    {
                        "ip": ip,
                        "port": port,
                        "status": "in_progress",
                        "last_synced": (
                            last_synced.isoformat() if last_synced else None
                        ),
                    }
                )
                validators[hotkey] = node_progress
                progress["validators"] = validators
                dynamic_config_service.set_sync_progress(progress)
                logger.info(
                    f"Starting first-time sync for validator {hotkey} at {ip}:{port}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to update sync progress to in_progress for {hotkey}: {e}"
                )
        base_url = f"http://{ip}:{port}"
        url = f"{base_url}/coupons/"
        responded_for_node = False
        node_had_coupons = False
        node_coupons_fetched = 0
        node_coupons_synced = 0

        # Preflight check: if peer is in first sync, skip it (only during our first sync)
        if is_first_sync and settings.respect_peer_sync:
            max_wait = int(
                settings.peer_sync_preflight_max_wait.total_seconds()
            )
            interval = int(
                settings.peer_sync_preflight_interval.total_seconds()
            )
            waited = 0
            try:
                async with httpx.AsyncClient(
                    timeout=5, follow_redirects=True
                ) as client:
                    while waited < max_wait:
                        try:
                            sync_resp = await client.get(
                                f"{base_url}/info/sync"
                            )
                            sync_resp.raise_for_status()
                            sync_json = sync_resp.json()
                            peer_in_first_sync = bool(
                                sync_json.get("progress")
                            )
                            if peer_in_first_sync:
                                logger.info(
                                    f"Skipping {hotkey} for now: peer is in first sync (waited {waited}s)"
                                )
                                # Sleep and retry preflight
                                await asyncio.sleep(interval)
                                waited += interval
                                continue
                            else:
                                logger.info(
                                    f"Peer {hotkey} not in first sync; proceeding with syncing"
                                )
                                break
                        except Exception:
                            # Could be down; wait and retry preflight
                            await asyncio.sleep(interval)
                            waited += interval
            except Exception:
                # Ignore preflight errors and proceed
                pass

        try:
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
            ) as client:
                while True:
                    params = dict(sort_by="last_action_date")
                    if last_synced:
                        params["last_action_from"] = last_synced

                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    coupons_json = resp.json()

                    # Convert JSON to CouponResponse objects using TypeAdapter
                    coupon_adapter = TypeAdapter(List[CouponResponse])
                    coupons = coupon_adapter.validate_python(coupons_json)

                    if not responded_for_node:
                        responded_total += 1
                        responded_for_node = True

                    if not coupons:
                        if not node_had_coupons:
                            logger.warning(f"No coupons found for {hotkey}")
                            empty_total += 1
                            if is_first_sync:
                                try:
                                    progress = (
                                        dynamic_config_service.get_sync_progress()
                                        or {}
                                    )
                                    validators = progress.get("validators", {})
                                    node_progress = validators.get(hotkey, {})
                                    node_progress.update(
                                        {
                                            "status": "done",
                                            "coupons_fetched": 0,
                                            "synced": 0,
                                        }
                                    )
                                    validators[hotkey] = node_progress
                                    progress["validators"] = validators
                                    dynamic_config_service.set_sync_progress(
                                        progress
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Failed to update sync progress to done (no data) for {hotkey}: {e}"
                                    )
                        break

                    # We have coupons in this batch
                    if not node_had_coupons:
                        validators_with_coupons_total += 1
                        node_had_coupons = True

                    logger.info(
                        f"Processing {len(coupons)} coupons from {hotkey}"
                    )
                    coupons_fetched_total += len(coupons)
                    node_coupons_fetched += len(coupons)

                    try:
                        responses = coupon_service.sync_coupons_batch(
                            coupons,
                            source_hotkey=hotkey,
                        )
                        logger.info(
                            f"Synced {len(responses)} coupons from {hotkey}"
                        )
                        processed_total_synced += len(responses)
                        node_coupons_synced += len(responses)
                    except Exception as e:
                        logger.error(
                            f"Failed to sync coupons batch from {hotkey}: {e}"
                        )
                        if is_first_sync:
                            try:
                                progress = (
                                    dynamic_config_service.get_sync_progress()
                                    or {}
                                )
                                validators = progress.get("validators", {})
                                node_progress = validators.get(hotkey, {})
                                node_progress.update(
                                    {
                                        "status": "error",
                                        "error": str(e),
                                    }
                                )
                                validators[hotkey] = node_progress
                                progress["validators"] = validators
                                dynamic_config_service.set_sync_progress(
                                    progress
                                )
                            except Exception as e2:
                                logger.error(
                                    f"Failed to update sync progress to error for {hotkey}: {e2}"
                                )
                        errors_total += 1

                    # Update last synced timestamp (use the max last_action_at from coupons)
                    max_last_action_date = max(
                        coupons, key=lambda x: x.last_action_at
                    ).last_action_at
                    validator_sync_offset_service.set_last_coupon_action_date(
                        hotkey, max_last_action_date
                    )

                    # Advance cursor slightly to avoid re-fetching equal timestamps
                    last_synced = max_last_action_date

                # end while

                if is_first_sync and responded_for_node:
                    try:
                        progress = (
                            dynamic_config_service.get_sync_progress() or {}
                        )
                        validators = progress.get("validators", {})
                        node_progress = validators.get(hotkey, {})
                        node_progress.update(
                            {
                                "status": (
                                    "done" if node_had_coupons else "done"
                                ),
                                "coupons_fetched": node_coupons_fetched,
                                "synced": node_coupons_synced,
                                "last_synced": (
                                    last_synced.isoformat()
                                    if last_synced
                                    else None
                                ),
                            }
                        )
                        validators[hotkey] = node_progress
                        progress["validators"] = validators
                        dynamic_config_service.set_sync_progress(progress)
                    except Exception as e:
                        logger.error(
                            f"Failed to update sync progress to done for {hotkey}: {e}"
                        )
        except Exception as e:
            logger.error(f"Failed to sync coupons for validator {hotkey}: {e}")
            if is_first_sync:
                try:
                    progress = dynamic_config_service.get_sync_progress() or {}
                    validators = progress.get("validators", {})
                    node_progress = validators.get(hotkey, {})
                    node_progress.update(
                        {
                            "status": "error",
                            "error": str(e),
                        }
                    )
                    validators[hotkey] = node_progress
                    progress["validators"] = validators
                    dynamic_config_service.set_sync_progress(progress)
                except Exception as e2:
                    logger.error(
                        f"Failed to update sync progress to error for {hotkey}: {e2}"
                    )
            errors_total += 1

    if is_first_sync:
        # Process sequentially to avoid race conditions on progress updates
        for node in validator_nodes:
            await fetch_and_store(node)
    else:
        await asyncio.gather(
            *(fetch_and_store(node) for node in validator_nodes)
        )

    # Finalize status and clear sync progress
    try:
        status = "ok"
        if errors_total > 0:
            status = "error"
        elif (
            processed_total_synced == 0 and validators_with_coupons_total == 0
        ):
            status = "empty"

        result_payload = {
            "finished_at": datetime.now(UTC).isoformat(),
            "status": status,
            "validators_total": len(validator_nodes),
            "responded_validators": responded_total,
            "validators_with_coupons": validators_with_coupons_total,
            "errors": errors_total,
            "empty_responses": empty_total,
            "coupons_fetched": coupons_fetched_total,
            "coupons_synced": processed_total_synced,
        }
        dynamic_config_service.set_last_sync_result(result_payload)
        # Clear sync progress after each sync run
        dynamic_config_service.set_sync_progress()
        logger.info("Coupon sync finalized and progress cleared")
    except Exception as e:
        logger.error(f"Failed to finalize sync status: {e}")


if __name__ == "__main__":
    settings = dependencies.get_settings()
    db = next(dependencies.get_db())
    metagraph_service = dependencies.get_metagraph_service(db=db)
    dynamic_config_service = dependencies.get_dynamic_config_service(db=db)
    coupon_service = dependencies.get_coupon_service(
        db=db,
        settings=settings,
        metagraph_service=metagraph_service,
        dynamic_config_service=dynamic_config_service,
    )
    validator_sync_offset_service = (
        dependencies.get_validator_sync_offset_service(
            db=db,
        )
    )

    asyncio.run(
        sync_coupons(
            settings,
            coupon_service,
            validator_sync_offset_service,
            metagraph_service,
            True,
        )
    )
