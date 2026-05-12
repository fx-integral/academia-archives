import asyncio
from datetime import UTC, datetime, timedelta
from typing import List, Tuple, Optional

import httpx

from fiber.logging_utils import get_logger
from fiber.chain import chain_utils
from fiber.validator import client as validator

from subnet_validator.constants import CouponStatus
from subnet_validator.database.entities import Coupon, Site
from subnet_validator.services.validator.base import BaseCouponValidator


logger = get_logger(__name__)


class MinerJobFailed(Exception):
    """Raised when miner reports a failed job that should mark coupon invalid."""
    pass

class TlsnCouponValidator(BaseCouponValidator):
    def __init__(
        self,
        site: Site,
        verifier_url: str,
        *,
        settings,
        metagraph,
        coupon_service,
    ):
        self.site = site
        self.verifier_url = verifier_url.rstrip("/")
        self.settings = settings
        self.metagraph = metagraph
        self.coupon_service = coupon_service
        self._client: Optional[httpx.AsyncClient] = None
        # Load validator keypair
        self._keypair = chain_utils.load_hotkey_keypair(
            self.settings.wallet_name, self.settings.hotkey_name
        )

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(
                connect=5.0, read=20.0, write=10.0, pool=10.0
            )
            self._client = httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            )
        return self._client

    async def _close_client(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            finally:
                self._client = None

    async def _get_miner_node(self, coupon: Coupon):
        """Get miner node from metagraph."""
        miner_node = self.metagraph.get_node_by_hotkey(coupon.miner_hotkey)
        if not miner_node:
            logger.warning(
                "Miner not found in metagraph | miner_hotkey=%s",
                coupon.miner_hotkey,
            )
            return None
        return miner_node

    async def _create_job(self, coupon: Coupon, miner_node) -> Optional[str]:
        """Create a job with the miner and return job_id."""
        server_address = f"http://{miner_node.ip}:{miner_node.port}"
        miner_ss58 = coupon.miner_hotkey
        
        payload = {
            "coupon_code": coupon.code,
            "site_id": self.site.id,
            "miner_hotkey": coupon.miner_hotkey,
        }
        
        logger.info(
            "Requesting TLSN proof from miner | addr=%s site_id=%s code=%s",
            server_address,
            coupon.site_id,
            coupon.code,
        )
        
        httpx_client = await self._get_or_create_client()
        resp = await validator.make_non_streamed_post(
            httpx_client=httpx_client,
            server_address=server_address,
            keypair=self._keypair,
            validator_ss58_address=self._keypair.ss58_address,
            miner_ss58_address=miner_ss58,
            payload=payload,
            endpoint="/coupon/check",
        )
        resp.raise_for_status()
        job_data = resp.json()
        job_id = job_data.get("job_id")
        
        if not job_id:
            logger.warning(
                "Miner did not return job_id | response=%s", job_data
            )
            return None
            
        return job_id

    async def _check_job_status(self, job_id: str, coupon: Coupon, miner_node) -> Optional[str]:
        """Check job status and return proof if available."""
        server_address = f"http://{miner_node.ip}:{miner_node.port}"
        miner_ss58 = coupon.miner_hotkey
        
        httpx_client = await self._get_or_create_client()
        job_resp = await validator.make_non_streamed_get(
            httpx_client=httpx_client,
            server_address=server_address,
            validator_ss58_address=self._keypair.ss58_address,
            miner_ss58_address=miner_ss58,
            keypair=self._keypair,
            endpoint=f"/job/{job_id}",
        )
        job_resp.raise_for_status()
        job_json = job_resp.json()
        
        result = job_json.get("result")
        error = job_json.get("error")
        status = job_json.get("status")
        
        # Check for job status 4 (failure) - raise to indicate invalid
        if status == 4:
            logger.info("Miner job failed with status 4 | job_id=%s", job_id)
            raise MinerJobFailed("status=4")
        
        if error:
            logger.warning(
                "Miner job error | job_id=%s error=%s", job_id, error
            )
            return None
            
        # Validate job age vs deadline
        if not self._is_job_within_deadline(job_json, coupon):
            return None
            
        return self._extract_proof_from_result(result)

    def _is_job_within_deadline(self, job_json: dict, coupon: Coupon) -> bool:
        """Check if job was started within the deadline."""
        try:
            last_time = coupon.last_checked_at or coupon.created_at
            deadline = (
                last_time.replace(tzinfo=UTC)
                + self.settings.lose_ownership_delta
            )
            js = job_json.get("job_start_time")
            if isinstance(js, str) and js:
                iso = js.strip().replace("Z", "+00:00")
                job_started = datetime.fromisoformat(iso)
                if job_started.tzinfo is None:
                    job_started = job_started.replace(tzinfo=UTC)
                if job_started >= deadline:
                    logger.info(
                        "Job start time beyond deadline | job_start=%s deadline=%s",
                        job_started,
                        deadline,
                    )
                    return False
            return True
        except Exception as e:
            logger.debug(
                "Failed to compare job_start_time with deadline | err=%s",
                e,
            )
            return True  # Allow to proceed if deadline check fails

    def _extract_proof_from_result(self, result) -> Optional[str]:
        """Extract proof hex from job result."""
        if not result:
            return None
            
        if isinstance(result, str):
            return result
            
        if isinstance(result, dict):
            # Prefer nested {data} for presentation
            data_hex = result.get("data") or result.get("hex")
            if isinstance(data_hex, str):
                return data_hex
            logger.debug(
                "Unsupported result format from miner | result=%s",
                result,
            )
            return None
            
        return None

    async def _request_proof_from_miner(self, coupon: Coupon) -> Optional[str]:
        """Request a TLSN proof from the coupon owner miner and return hex-encoded presentation.

        Single attempt: submit job and try one immediate get; no polling/sleep.
        """
        try:
            # Get miner node
            miner_node = await self._get_miner_node(coupon)
            if not miner_node:
                return None
                
            # Create job
            job_id = await self._create_job(coupon, miner_node)
            if not job_id:
                return None
                
            # Check job status and get proof
            return await self._check_job_status(job_id, coupon, miner_node)
            
        except MinerJobFailed:
            # propagate to caller for marking coupon invalid
            raise
        except Exception as e:
            logger.exception(
                "Failed to request proof from miner | code=%s err=%s",
                coupon.code,
                e,
            )
            return None

    def _validate_proof_metadata(self, meta: dict, coupon: Coupon) -> bool:
        """Validate that the proof metadata matches the site's configuration requirements."""
        try:
            if not isinstance(meta, dict) or not isinstance(self.site.config, dict):
                return True  # Skip validation if no config available
            
            site_config = self.site.config
            data = meta.get("data", {})
            sent = data.get("sent", "")
            received = data.get("received", "")
            
            # Check requestParams if configured
            request_params = site_config.get("requestParams")
            if request_params and isinstance(request_params, dict):
                expected_method = request_params.get("method", "POST")
                expected_url = request_params.get("applyCouponUrl")
                
                if expected_url and expected_method:
                    # Check if the sent request matches expected method and URL
                    if not (sent.startswith(expected_method) and expected_url in sent):
                        logger.warning(
                            "Proof metadata doesn't match expected request | sent=%s expected=%s %s",
                            sent, expected_method, expected_url
                        )
                        return False
            
            
            return True
        except Exception as e:
            logger.warning("Error validating proof metadata | err=%s", e)
            return True  # Allow validation to pass on error

    async def _verify_proof(
        self, presentation_hex: str, coupon: Coupon
    ) -> tuple[Optional[bool], Optional[dict]]:
        try:
            client = await self._get_or_create_client()
            resp = await client.post(
                self.verifier_url,
                json={"data": presentation_hex},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            valid = data.get("valid")
            # Extract rich metadata for storage
            meta: dict = {}
            if isinstance(data.get("server_name"), str):
                meta["server_name"] = data["server_name"]
            if isinstance(data.get("timestamp"), str):
                meta["timestamp"] = data["timestamp"]
            vk = data.get("verifying_key")
            if isinstance(vk, dict):
                alg = vk.get("algorithm")
                kd = vk.get("key_data")
                inner: dict = {}
                if isinstance(alg, str):
                    inner["algorithm"] = alg
                if isinstance(kd, str):
                    inner["key_data"] = kd
                if inner:
                    meta["verifying_key"] = inner
            d = data.get("data")
            if isinstance(d, dict):
                received = d.get("received")
                sent = d.get("sent")
                rec_obj: dict = {}
                if isinstance(received, str):
                    # Truncate to avoid overly large payloads in DB
                    rec_obj["received"] = received
                if isinstance(sent, str):
                    rec_obj["sent"] = sent
                if rec_obj:
                    meta["data"] = rec_obj
            
            # Validate metadata against site configuration
            if valid and meta:
                if not self._validate_proof_metadata(meta, coupon):
                    valid = False
                    logger.info("Proof metadata validation failed, marking as invalid")
            
            return (
                valid if isinstance(valid, bool) else None,
                meta if meta else None,
            )
        except Exception as e:
            logger.exception("TLSN verify error | err=%s", e)
            return (None, None)

    async def validate(
        self, coupons: List[Coupon]
    ) -> List[Tuple[Coupon, bool]]:
        results: List[Tuple[Coupon, bool]] = []
        try:
            for coupon in coupons:
                try:
                    # 1) Ask miner for proof
                    proof_hex = await self._request_proof_from_miner(coupon)
                    result = None
                    if proof_hex:
                        # 2) Verify proof locally
                        result, meta = await self._verify_proof(proof_hex, coupon)
                        # Persist tlsn metadata under rule.tlsn
                        try:
                            if meta:
                                existing_rule = getattr(coupon, "rule", None)
                                if not isinstance(existing_rule, dict):
                                    existing_rule = {}
                                existing_rule["tlsn"] = meta
                                coupon.rule = existing_rule
                        except Exception:
                            pass
                    if result is True:
                        coupon.status = CouponStatus.VALID
                        coupon.last_checked_at = datetime.now(UTC)
                    elif result is False:
                        coupon.status = CouponStatus.INVALID
                        coupon.last_checked_at = datetime.now(UTC)
                    else:
                        # No definitive result; check ownership timeout window
                        last_time = coupon.last_checked_at or coupon.created_at
                        deadline = (
                            last_time.replace(tzinfo=UTC)
                            + self.settings.lose_ownership_delta
                        )
                        if datetime.now(UTC) > deadline:
                            # Mark as deleted and clear ownership
                            coupon.status = CouponStatus.DELETED
                            coupon.deleted_at = datetime.now(UTC)
                            try:
                                self.coupon_service._clear_coupon_ownership(
                                    site_id=coupon.site_id, code=coupon.code
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to clear ownership | site_id=%s code=%s err=%s",
                                    coupon.site_id,
                                    coupon.code,
                                    e,
                                )
                            coupon.last_checked_at = datetime.now(UTC)
                            results.append((coupon, False))
                            continue
                        # Keep coupon unchanged (pending and no last_checked_at update)
                    results.append(
                        (
                            coupon,
                            (
                                result is True
                                if isinstance(result, bool)
                                else False
                            ),
                        )
                    )
                except MinerJobFailed:
                    # Handle miner job failure - mark as invalid
                    logger.info("Miner job failed, marking coupon invalid | code=%s", coupon.code)
                    coupon.status = CouponStatus.INVALID
                    coupon.last_checked_at = datetime.now(UTC)
                    results.append((coupon, False))
                except Exception as e:
                    logger.exception(
                        "Error validating coupon via TLSN | code=%s err=%s",
                        coupon.code,
                        e,
                    )
                    try:
                        coupon.last_checked_at = datetime.now(UTC)
                    except Exception:
                        pass
                    results.append((coupon, False))
        finally:
            await self._close_client()
        return results
