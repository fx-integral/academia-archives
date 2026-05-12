import asyncio
import traceback
from api import config
from utils import logger
from rules.set_builder import EvaluationSetBuilder
from utils.subtensor import get_subtensor

async def validator_evaluation_set_builder_loop():
    logger.info("Starting validator evaluation set builder loop...")
    count = 0
    first = True
    while True:
        if not first:
            try:
                count += 1
                current_block = await get_current_block()
                builder = EvaluationSetBuilder(current_block=current_block)
                new_eval_set = builder.build_evaluation_set()
                logger.info("=== Validator Evaluation Set Builder Loop ===")
                logger.info(f"Current block: {current_block}")
                logger.info(f"New set: {new_eval_set}")
                logger.info(f"Validator evaluation set builder loop complete - loop {count}")
            except Exception as e:
                logger.error(f"Error in validator evaluation set builder loop: {e}")
                logger.error(traceback.format_exc())
        first = False
        await asyncio.sleep(config.VALIDATOR_SET_BUILDER_LOOP_INTERVAL_SECONDS)
        

async def get_current_block() -> int:
    sub = await get_subtensor()
    current_block = await sub.get_current_block()
    return current_block
    