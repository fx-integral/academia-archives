import asyncio
import json
import os
import subprocess
import tempfile
import logging
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Tuple, Callable, Optional

from subnet_validator.constants import CouponStatus
from fiber.logging_utils import get_logger
from subnet_validator.database.entities import Coupon, Site
from subnet_validator.services.validator.base import BaseCouponValidator


logger = get_logger(__name__)


class PlaywrightCouponValidator(BaseCouponValidator):
    def __init__(self, site: Site, path: Path):
        self.site = site
        self.node_script_path = path

    async def _stream_subprocess_output(
        self,
        stream: asyncio.StreamReader,
        level: int,
        prefix: str,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Stream subprocess output line-by-line to logger, calling on_line for each decoded line if provided."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    text = line.decode(errors="replace").rstrip()
                except Exception:
                    text = str(line)
                logger.log(level, "%s%s", prefix, text)
                if on_line is not None:
                    try:
                        on_line(text)
                    except Exception as cb_err:
                        logger.debug("on_line callback raised: %s", cb_err)
        except Exception as e:
            logger.warning("Error while streaming subprocess output: %s", e)

    async def _run_node_validation(
        self, coupon: Coupon, site_config: dict
    ) -> Optional[bool]:
        """Run the Node.js validation script as a subprocess.
        Returns True for valid, False for invalid, None for unknown (e.g., timeout/error).
        """
        try:
            # Create temporary directory for output
            with tempfile.TemporaryDirectory() as temp_dir:
                # Prepare the command
                # Use ASCII-escaped JSON to avoid CLI parsing issues on Node side (emojis, special chars)
                config_arg = json.dumps(
                    site_config, ensure_ascii=True, separators=(",", ":")
                )
                cmd = [
                    "node",
                    str(self.node_script_path),
                    f"--coupon={coupon.code}",
                    f"--domain={self.site.base_url}",
                    f"--config={config_arg}",
                ]
                if coupon.used_on_product_url:
                    cmd.append(
                        f"--used_on_product_url={coupon.used_on_product_url}"
                    )
                logger.info(
                    "Starting Node.js validation subprocess | coupon=%s site=%s cwd=%s cmd=%s",
                    coupon.code,
                    self.site.base_url,
                    temp_dir,
                    " ".join(map(str, cmd)),
                )

                # Run the subprocess
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=temp_dir,
                )
                # Stream stdout/stderr in real time
                success_seen = False
                parse_error_seen = False
                stderr_lines = 0

                def check_success(line: str) -> None:
                    nonlocal success_seen
                    if ("Coupon is valid" in line) or ("🎉" in line):
                        success_seen = True

                stdout_task = asyncio.create_task(
                    self._stream_subprocess_output(
                        process.stdout,
                        logging.INFO,
                        "node(stdout): ",
                        on_line=check_success,
                    )
                )

                def check_stderr(line: str) -> None:
                    nonlocal parse_error_seen, stderr_lines
                    stderr_lines += 1
                    if (
                        "Invalid JSON in --config" in line
                        or "SyntaxError" in line
                    ):
                        parse_error_seen = True

                stderr_task = asyncio.create_task(
                    self._stream_subprocess_output(
                        process.stderr,
                        logging.ERROR,
                        "node(stderr): ",
                        on_line=check_stderr,
                    )
                )

                try:
                    await asyncio.wait_for(
                        process.wait(), timeout=300
                    )  # 5 minute timeout
                except asyncio.TimeoutError:
                    logger.error(
                        "Node validation timed out after 300s | coupon=%s site=%s. Terminating...",
                        coupon.code,
                        self.site.base_url,
                    )
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    # Ensure we consume remaining output
                    await asyncio.gather(
                        stdout_task, stderr_task, return_exceptions=True
                    )
                    return None

                # Ensure all output was drained
                await asyncio.gather(
                    stdout_task, stderr_task, return_exceptions=True
                )

                logger.info(
                    "Node validation finished | coupon=%s site=%s return_code=%s",
                    coupon.code,
                    self.site.base_url,
                    process.returncode,
                )
                if process.returncode != 0:
                    logger.error(
                        "Node validation exited non-zero | coupon=%s site=%s return_code=%s",
                        coupon.code,
                        self.site.base_url,
                        process.returncode,
                    )
                    return None

                # Check if result.json was created and parse it
                result_file = Path(temp_dir) / "output" / "result.json"
                if result_file.exists():
                    with open(result_file, "r") as f:
                        result = json.load(f)
                        value = result.get("couponIsValid", None)
                        if isinstance(value, bool):
                            return value
                        return None

                # Fallback: check stdout for success indicators
                logger.debug(
                    "Result file not found | coupon=%s site=%s success_seen=%s stderr_lines=%s parse_error_seen=%s",
                    coupon.code,
                    self.site.base_url,
                    success_seen,
                    stderr_lines,
                    parse_error_seen,
                )
                return True if success_seen else None

        except Exception as e:
            logger.exception(
                "Error running Node.js validation | coupon=%s site=%s error=%s",
                coupon.code,
                self.site.base_url,
                e,
            )
            return None

    async def validate(
        self, coupons: List[Coupon]
    ) -> List[Tuple[Coupon, bool]]:
        """Validate coupons using the Node.js Playwright script"""
        results = []

        for coupon in coupons:
            try:
                # Create site configuration

                # Run validation
                config = self.site.config.copy()
                if coupon.used_on_product_url:
                    config["productUrl"] = coupon.used_on_product_url
                result = await self._run_node_validation(coupon, config)

                # Update coupon status only on definitive result; leave as-is on None
                if result is True:
                    coupon.status = CouponStatus.VALID
                elif result is False:
                    coupon.status = CouponStatus.INVALID
                # If result is None, keep existing status unchanged
                coupon.last_checked_at = datetime.now(UTC)

                results.append((coupon, result is True))

            except Exception as e:
                logger.exception(
                    "Error validating coupon %s: %s", coupon.code, e
                )
                # On unexpected errors, keep status as-is
                coupon.last_checked_at = datetime.now(UTC)
                results.append((coupon, False))

        return results
