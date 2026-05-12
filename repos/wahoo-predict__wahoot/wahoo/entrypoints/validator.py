import argparse
import logging
import os

from wahoo.validator.validator import (
    WAHOO_API_URL,
    WAHOO_VALIDATION_ENDPOINT,
    calculate_loop_interval,
    initialize_bittensor,
    main_loop_iteration,
)
from wahoo.validator.database.core import ValidatorDB
from wahoo.validator.database.validator_db import check_database_exists, get_db_path, run_alembic_migrations
from wahoo.validator.init import initialize


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WaHoo Predict Bittensor Validator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--netuid",
        type=int,
        default=int(os.getenv("NETUID", "0")),
        help="Subnet UID (required for production)",
    )
    parser.add_argument(
        "--network",
        type=str,
        default=os.getenv("NETWORK", "finney"),
        help="Bittensor network (test or finney). Default: finney",
    )
    parser.add_argument(
        "--chain-endpoint",
        type=str,
        default=os.getenv("CHAIN_ENDPOINT", None),
        dest="chain_endpoint",
        help="Custom chain endpoint URL (overrides network if set). For advanced use only.",
    )

    parser.add_argument(
        "--wallet.name",
        type=str,
        default=os.getenv("WALLET_NAME"),
        dest="wallet_name",
        required=os.getenv("WALLET_NAME") is None,
        help="Wallet name (coldkey). Required if WALLET_NAME env var not set.",
    )
    parser.add_argument(
        "--wallet.hotkey",
        type=str,
        default=os.getenv("HOTKEY_NAME"),
        dest="hotkey_name",
        required=os.getenv("HOTKEY_NAME") is None,
        help="Hotkey name. Required if HOTKEY_NAME env var not set.",
    )

    parser.add_argument(
        "--use-validator-db",
        action="store_true",
        default=os.getenv("USE_VALIDATOR_DB", "false").lower() == "true",
        dest="use_validator_db",
        help="Enable ValidatorDB caching",
    )
    parser.add_argument(
        "--validator-db-path",
        type=str,
        default=os.getenv("VALIDATOR_DB_PATH", "validator.db"),
        dest="validator_db_path",
        help="Path to validator database",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        dest="log_level",
        help="Logging level",
    )

    parser.add_argument(
        "--wahoo-api-url",
        type=str,
        default=os.getenv("WAHOO_API_URL", WAHOO_API_URL),
        dest="wahoo_api_url",
        help="WAHOO API URL (overrides default)",
    )
    parser.add_argument(
        "--wahoo-validation-endpoint",
        type=str,
        default=os.getenv("WAHOO_VALIDATION_ENDPOINT", WAHOO_VALIDATION_ENDPOINT),
        dest="wahoo_validation_endpoint",
        help="WAHOO validation endpoint URL (overrides default)",
    )
    parser.add_argument(
        "--loop-interval",
        type=float,
        default=None,
        dest="loop_interval",
        help="Override loop interval in seconds (default: calculated from metagraph)",
    )

    args = parser.parse_args()

    log_level = getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("WaHoo Predict Validator")
    logger.info("=" * 70)

    db_path = get_db_path()
    if not check_database_exists(db_path):
        logger.info("First run detected - initializing database...")
        try:
            initialize(skip_deps=True, skip_db=False, db_path=str(db_path))
            logger.info(f"✓ Database initialized successfully at {db_path}")
        except Exception as e:
            logger.warning(f"Auto-initialization failed: {e}")
            logger.info("You can manually run: wahoo-validator-init")
            logger.info("Continuing anyway...")
    else:
        logger.debug(f"Database exists at {db_path}")

    # Run alembic migrations to ensure schema is up to date
    try:
        run_alembic_migrations(db_path)
    except Exception as e:
        logger.warning(f"Failed to run migrations: {e}")
        logger.info("Continuing with existing schema...")

    if not args.wallet_name or not args.hotkey_name:
        logger.error(
            "WALLET_NAME and HOTKEY_NAME must be set. "
            "Set via environment variables (WALLET_NAME, HOTKEY_NAME) or CLI arguments (--wallet.name, --wallet.hotkey)."
        )
        return

    config = {
        "netuid": args.netuid,
        "network": args.network,
        "wallet_name": args.wallet_name,
        "hotkey_name": args.hotkey_name,
        "use_validator_db": args.use_validator_db,
        "wahoo_api_url": args.wahoo_api_url,
        "wahoo_validation_endpoint": args.wahoo_validation_endpoint,
        "chain_endpoint": args.chain_endpoint,
    }

    logger.info("Configuration:")
    logger.info(f"  Network: {config['network']}")
    logger.info(f"  Subnet UID: {config['netuid']}")
    logger.info(f"  Wallet: {config['wallet_name']}/{config['hotkey_name']}")
    logger.info(f"  ValidatorDB: {config['use_validator_db']}")
    logger.info(f"  WAHOO API: {WAHOO_API_URL}")

    try:
        wallet, subtensor, dendrite, metagraph = initialize_bittensor(
            wallet_name=config["wallet_name"],
            hotkey_name=config["hotkey_name"],
            netuid=config["netuid"],
            network=config["network"],
            chain_endpoint=config.get("chain_endpoint"),
        )
    except Exception as e:
        logger.error(f"Failed to initialize Bittensor: {e}")
        return

    # Calculate loop interval from metagraph if not provided
    # Default behavior is to calculate from metagraph tempo
    if args.loop_interval is not None:
        loop_interval = args.loop_interval
        logger.info(
            f"  Loop interval: {loop_interval:.1f}s (override from command line)"
        )
    else:
        loop_interval = calculate_loop_interval(metagraph, subtensor=subtensor)
        logger.info(
            f"  Loop interval: {loop_interval:.1f}s (calculated from metagraph tempo)"
        )

    validator_db = None
    if config["use_validator_db"]:
        try:
            validator_db = ValidatorDB(db_path=get_db_path())
            logger.info(f"ValidatorDB initialized at {get_db_path()}")
        except Exception as e:
            logger.error(f"Failed to initialize ValidatorDB: {e}")
            logger.warning("Continuing without database support")

    logger.info("Entering main loop...")
    logger.info("Press Ctrl+C to stop")

    import time

    iteration_count = 0
    try:
        while True:
            main_loop_iteration(
                wallet=wallet,
                subtensor=subtensor,
                dendrite=dendrite,
                metagraph=metagraph,
                netuid=config["netuid"],
                config=config,
                validator_db=validator_db,
                iteration_count=iteration_count,
            )
            iteration_count += 1

            # Recalculate loop interval from metagraph if not overridden
            # This allows the interval to adapt if metagraph tempo changes
            if args.loop_interval is None:
                loop_interval = calculate_loop_interval(metagraph, subtensor=subtensor)
            logger.info(f"Sleeping for {loop_interval:.1f}s before next iteration...")
            time.sleep(loop_interval)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}", exc_info=True)
    finally:
        logger.info("Validator stopped")


if __name__ == "__main__":
    main()
