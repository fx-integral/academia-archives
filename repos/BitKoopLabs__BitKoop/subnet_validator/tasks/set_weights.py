import asyncio
from datetime import (
    timedelta,
)
import time

from fiber import SubstrateInterface
from fiber.chain import (
    interface,
    chain_utils,
)

from fiber.chain.models import Node
from fiber.chain.chain_utils import Keypair
from subnet_validator.database.database import get_db
from subnet_validator.dependencies import (
    get_metagraph_service,
    get_settings,
)
from subnet_validator.services.dynamic_config_service import (
    DynamicConfigService,
)
from subnet_validator.services.metagraph_service import MetagraphService
from subnet_validator.services.weight_calculator_service import (
    WeightCalculatorService,
)
from fiber.logging_utils import (
    get_logger,
)
from sqlalchemy.orm import Session
from fiber.chain.fetch_nodes import (
    get_nodes_for_netuid,
)
from subnet_validator.settings import Settings
from fiber.chain import chain_utils, weights
from fiber.chain.fetch_nodes import get_nodes_for_netuid
from subnet_validator import __spec_version__ as version_key

logger = get_logger(__name__)


async def set_weights(
    db: Session,
    weight_calculator: WeightCalculatorService,
    dynamic_config_service: DynamicConfigService,
    context=None,
    **kwargs,
):
    """
    Main function to calculate and set weights for all miners.
    """
    # Use context.get_settings() if available, otherwise fallback to direct call
    if context:
        settings = context.get_settings()
    else:
        from . import dependencies

        settings = dependencies.get_settings()

    last_set_weights_time = dynamic_config_service.get_last_set_weights_time()
    if (
        last_set_weights_time
        > time.time() - settings.set_weights_interval.total_seconds()
    ):
        logger.debug(
            "Skipping weight calculation because it was already run recently"
        )
        return

    logger.info("Starting weight calculation...")

    # Get database session

    try:
        # Calculate weights using the service
        scores = weight_calculator.calculate_weights()

        # if not any(scores.values()):
        #     logger.warning("All ratings are 0, skipping weight set")
        #     return

        keypair = chain_utils.load_hotkey_keypair(
            wallet_name=settings.wallet_name, hotkey_name=settings.hotkey_name
        )

        # Get metagraph from context or factory config
        if context:
            metagraph = context.metagraph
        else:
            # Fallback to factory config
            from . import dependencies

            factory_config = dependencies.get_factory_config()
            metagraph = factory_config.metagraph

        # Check if metagraph is synced and has nodes
        if not metagraph.is_in_sync:
            logger.warning(
                "Metagraph is not synced, skipping weight calculation"
            )
            return

        # Get nodes from metagraph
        miner_nodes = metagraph.get_miner_nodes()
        validator_node = metagraph.get_node_by_hotkey(keypair.ss58_address)

        # Validate we have nodes
        if not miner_nodes:
            logger.warning("No miner nodes found in metagraph")
            return

        if not validator_node:
            logger.error(
                f"Validator node not found for hotkey {keypair.ss58_address}"
            )
            logger.info(
                f"Available nodes: {[node.hotkey for node in metagraph.nodes]}"
            )
            raise ValueError(
                f"Validator node not found for hotkey {keypair.ss58_address}"
            )
        validator_node_id = validator_node.node_id

        hotkey_to_node_id = {node.hotkey: node.node_id for node in miner_nodes}
        node_id_to_weight = {
            hotkey_to_node_id[hotkey]: score
            for hotkey, score in scores.items()
            if hotkey in hotkey_to_node_id
        }

        if not node_id_to_weight:
            logger.warning(
                "No node weights to set, fallback to hardcoded weights to subnet owner"
            )

            node_id_to_weight = {
                207: 1.0,
            }

        result = weights.set_node_weights(
            substrate=metagraph.substrate,
            keypair=keypair,
            node_ids=list(node_id_to_weight.keys()),
            node_weights=list(node_id_to_weight.values()),
            netuid=settings.netuid,
            validator_node_id=validator_node_id,
            version_key=version_key,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )

        if not result:
            raise Exception("Failed to set weights")

        dynamic_config_service.set_last_set_weights_time(time.time())

        logger.info("Weight calculation completed successfully")

        return scores

    except Exception as e:
        logger.error(f"Error during weight calculation: {e}", exc_info=True)
        raise
    finally:
        db.close()


async def periodic_set_weights(
    settings: Settings,
    substrate: SubstrateInterface,
    db: Session,
    weight_calculator: WeightCalculatorService,
    metagraph_service: MetagraphService,
    dynamic_config_service: DynamicConfigService,
    set_weights_interval: timedelta,
):
    """
    Periodic task to run set_weights at specified intervals.
    """
    while True:
        logger.info("Starting set_weights cycle.")
        try:
            await set_weights(
                settings,
                substrate,
                db,
                weight_calculator,
                metagraph_service,
                dynamic_config_service,
            )
        except Exception as e:
            logger.error(f"Error in set_weights cycle: {e}", exc_info=True)

        logger.info(
            f"Sleeping for {set_weights_interval.total_seconds()} seconds before next set_weights cycle."
        )
        await asyncio.sleep(set_weights_interval.total_seconds())


def _get_validator_node_id(keypair: Keypair, nodes: list[Node]) -> int:
    try:
        return next(
            node for node in nodes if node.hotkey == keypair.ss58_address
        ).node_id
    except StopIteration:
        message = f"Validator node not found for hotkey {keypair.ss58_address}"
        logger.error(message)
        raise ValueError(message)


if __name__ == "__main__":
    settings = get_settings()
    db = get_db()
    metagraph_service = get_metagraph_service(db=db)
    weight_calculator = WeightCalculatorService(db=db)
    substrate = interface.get_substrate(
        subtensor_network=settings.subtensor_network
    )

    async def main():
        await set_weights(
            settings, substrate, db, weight_calculator, metagraph_service
        )

    asyncio.run(main())
