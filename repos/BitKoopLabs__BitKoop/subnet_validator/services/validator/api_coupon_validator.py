from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Tuple, Optional
from urllib.parse import quote, parse_qsl, urlencode, urlparse, urlunparse

from datetime import UTC, datetime
import httpx
import os
from bs4 import BeautifulSoup

from fiber.logging_utils import get_logger
from subnet_validator.constants import CouponStatus
from subnet_validator.database.entities import Coupon, Site
from subnet_validator.services.validator.base import BaseCouponValidator


logger = get_logger(__name__)


class ApiCouponValidator(BaseCouponValidator):
    """Validate coupons by calling a site's HTTP API.

    The site's `api_url` may contain the placeholder `{CODE}`, which will be replaced
    with the URL-encoded coupon code. Example:
        https://example-store.com/apps/coupon-check?code={CODE}

    Behavior mirrors PlaywrightCouponValidator: returns True/False/None and updates
    coupon status/time only on definitive results.
    """

    def __init__(
        self, site: Site, storefront_password: str | None = None
    ) -> None:
        self.site = site
        self._client: Optional[httpx.AsyncClient] = None
        self._storefront_logged_in: bool = False
        self._storefront_password = storefront_password

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # 10s connect, 25s read, total 30s
            timeout = httpx.Timeout(
                connect=10.0, read=25.0, write=10.0, pool=10.0
            )
            # Important: Create client with cookies enabled to maintain session
            self._client = httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, cookies=httpx.Cookies()
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

    @staticmethod
    def _base_from_api_url(api_url: str) -> Optional[str]:
        try:
            from urllib.parse import (
                urlparse as _urlparse,
                urlunparse as _urlunparse,
            )

            u = _urlparse(api_url)
            if not u.scheme or not u.netloc:
                return None
            return _urlunparse((u.scheme, u.netloc, "", "", "", ""))
        except Exception:
            return None

    async def _fetch_password_form(
        self, client: httpx.AsyncClient, store_base: str
    ) -> Optional[httpx.Response]:
        try:
            pwd_url = store_base.rstrip("/") + "/password"
            r = await client.get(pwd_url)
            r.raise_for_status()
            return r
        except Exception as e:
            logger.error(
                "Failed to GET password page | base=%s error=%s", store_base, e
            )
            return None

    @staticmethod
    def _parse_password_payload(
        resp: httpx.Response, storefront_password: str
    ) -> dict:
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            form = soup.find("form")
            if not form:
                return {
                    "form_type": "storefront_password",
                    "utf8": "✓",
                    "password": storefront_password,
                }
            payload: dict[str, str] = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                if not name:
                    continue
                value = inp.get("value", "")
                payload[name] = value
            payload["form_type"] = payload.get(
                "form_type", "storefront_password"
            )
            payload["utf8"] = payload.get("utf8", "✓")
            payload["password"] = storefront_password
            return payload
        except Exception:
            return {
                "form_type": "storefront_password",
                "utf8": "✓",
                "password": storefront_password,
            }

    async def _submit_password(
        self, client: httpx.AsyncClient, store_base: str, payload: dict
    ) -> bool:
        try:
            pwd_url = store_base.rstrip("/") + "/password"
            headers = {
                "Referer": pwd_url,
                "Origin": store_base,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            r = await client.post(
                pwd_url, data=payload, headers=headers, follow_redirects=True
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(
                "Failed to POST storefront password | base=%s error=%s",
                store_base,
                e,
            )
            return False

    async def _storefront_access_ok(
        self, client: httpx.AsyncClient, store_base: str
    ) -> bool:
        try:
            r = await client.get(
                store_base.rstrip("/") + "/", follow_redirects=True
            )
            return "/password" not in str(r.url)
        except Exception:
            return False

    def _get_storefront_password(self) -> Optional[str]:
        # Prefer site.config value if present, else env, else None
        try:
            if self._storefront_password:
                return self._storefront_password
            if isinstance(self.site.config, dict):
                pwd = self.site.config.get("storefront_password")
                if isinstance(pwd, str) and pwd:
                    return pwd
        except Exception:
            pass
        env_pwd = os.getenv("SHOPIFY_STOREFRONT_PASSWORD")
        if env_pwd:
            return env_pwd
        return None

    async def _ensure_storefront_login(
        self, client: httpx.AsyncClient, api_url: str
    ) -> None:
        if self._storefront_logged_in:
            return
        store_base = self._base_from_api_url(api_url)
        if not store_base:
            return
        storefront_password = self._get_storefront_password()
        if not storefront_password:
            # No password configured; nothing to do
            return
        logger.info(
            "Attempting Shopify storefront login | base=%s", store_base
        )
        form_resp = await self._fetch_password_form(client, store_base)
        if form_resp is None:
            return
        payload = self._parse_password_payload(form_resp, storefront_password)
        ok = await self._submit_password(client, store_base, payload)
        if not ok:
            return
        if await self._storefront_access_ok(client, store_base):
            logger.info("Storefront login successful | base=%s", store_base)
            self._storefront_logged_in = True
        else:
            logger.warning(
                "Storefront password not accepted or still gated | base=%s",
                store_base,
            )

    def _build_url(self, coupon: Coupon) -> Optional[str]:
        template = (self.site.api_url or "").strip()
        if not template:
            return None
        code_escaped = quote(coupon.code, safe="")
        try:
            # Replace {CODE} placeholder
            url_str = template.replace("{CODE}", code_escaped)
            # Append miner hotkey as hot_key query parameter for logging
            try:
                parsed = urlparse(url_str)
                query_params = dict(
                    parse_qsl(parsed.query, keep_blank_values=True)
                )
                if getattr(coupon, "miner_hotkey", None):
                    query_params.setdefault("hot_key", coupon.miner_hotkey)
                new_query = urlencode(query_params)
                url_str = urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        new_query,
                        parsed.fragment,
                    )
                )
            except Exception as _e:
                logger.debug(
                    "Failed to append hot_key to URL, proceeding without it | err=%s",
                    _e,
                )
            return url_str
        except Exception as e:
            logger.warning(
                "Failed to build URL from template | template=%s error=%s",
                template,
                e,
            )
            return None

    @staticmethod
    def _interpret_boolean_response(
        text: str, data: Optional[dict]
    ) -> Optional[bool]:
        """Attempt to interpret the remote response as a True/False result.

        Heuristics:
        - JSON keys (case-insensitive): couponIsValid, is_valid, valid, success, result
        - If not JSON: look for 'true'/'false' tokens in plain text
        """
        if isinstance(data, dict):
            lowered = {k.lower(): v for k, v in data.items()}

            # If response provides validity window, enforce it strictly
            def _parse_iso_datetime(value: object) -> Optional[datetime]:
                try:
                    if not isinstance(value, str):
                        return None
                    s = value.strip()
                    if not s:
                        return None
                    # Support trailing Z
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    else:
                        dt = dt.astimezone(UTC)
                    return dt
                except Exception:
                    return None

            def _extract_validity_bounds(
                payload: dict,
            ) -> tuple[Optional[datetime], Optional[datetime]]:
                starts_str: Optional[str] = None
                ends_str: Optional[str] = None
                try:
                    if isinstance(payload, dict):
                        raw_rule = payload.get("rule")
                        rule_dict = (
                            raw_rule if isinstance(raw_rule, dict) else None
                        )
                        v = payload.get("starts_at")
                        if isinstance(v, str):
                            starts_str = v
                        elif rule_dict:
                            v = rule_dict.get("starts_at")
                            if isinstance(v, str):
                                starts_str = v
                        v = payload.get("ends_at")
                        if isinstance(v, str):
                            ends_str = v
                        elif rule_dict:
                            v = rule_dict.get("ends_at")
                            if isinstance(v, str):
                                ends_str = v
                except Exception:
                    pass
                return _parse_iso_datetime(starts_str), _parse_iso_datetime(
                    ends_str
                )

            starts_dt, ends_dt = _extract_validity_bounds(data)
            if starts_dt or ends_dt:
                now_utc = datetime.now(UTC)
                if starts_dt and now_utc < starts_dt:
                    return False
                if ends_dt and now_utc > ends_dt:
                    return False

            # Helper: if rule.is_for_all_customers is explicitly False → treat as invalid
            def violates_all_customers_rule(payload: dict) -> bool:
                try:
                    rule = (
                        payload.get("rule")
                        if isinstance(payload, dict)
                        else None
                    )
                    if isinstance(rule, dict):
                        is_all = rule.get("is_for_all_customers")
                        if isinstance(is_all, bool) and is_all is False:
                            return True
                except Exception:
                    pass
                return False

            # Shopify canonical format: { ok: true, applicable: true/false, status: 'valid'|'invalid', ... }
            ok_val = lowered.get("ok")
            applicable_val = lowered.get("applicable")
            if ok_val is True and isinstance(applicable_val, bool):
                if applicable_val is True and violates_all_customers_rule(
                    data
                ):
                    return False
                return applicable_val

            # Fallback to 'status' field if present
            status_val = lowered.get("status")
            if isinstance(status_val, str):
                sv = status_val.strip().lower()
                if sv in ("valid", "applicable", "ok", "active", "enabled"):
                    if violates_all_customers_rule(data):
                        return False
                    return True
                if sv in ("invalid", "not_applicable", "error"):
                    return False

            # Generic candidates
            candidates = [
                "couponIsValid",
                "is_valid",
                "isValid",
                "valid",
                "success",
                "result",
            ]
            for key in candidates:
                v = lowered.get(key.lower())
                if isinstance(v, bool):
                    if v is True and violates_all_customers_rule(data):
                        return False
                    return v
                if isinstance(v, str):
                    lv = v.strip().lower()
                    if lv in ("true", "valid", "ok", "yes", "1"):
                        if violates_all_customers_rule(data):
                            return False
                        return True
                    if lv in ("false", "invalid", "no", "0"):
                        return False
                if isinstance(v, (int, float)):
                    if v in (1,):
                        if violates_all_customers_rule(data):
                            return False
                        return True
                    if v in (0,):
                        return False
        # Fallback to very strict plain text heuristics only
        lt = (text or "").strip().lower()
        if lt:
            # Highest priority: explicit "invalid"
            if (
                lt == "invalid"
                or '"status":"invalid"' in lt
                or '"applicable":false' in lt
            ):
                return False
            # Accept only exact booleans or explicit applicable:true
            if lt == "true" or lt == "false":
                return lt == "true"
            if '"applicable":true' in lt:
                return True
        return None

    async def _verify_session_still_valid(
        self, client: httpx.AsyncClient, api_url: str
    ) -> bool:
        """Verify that our session is still valid by checking if we can access the store."""
        try:
            store_base = self._base_from_api_url(api_url)
            if not store_base:
                return False
            return await self._storefront_access_ok(client, store_base)
        except Exception:
            return False

    async def _check_coupon(self, coupon: Coupon) -> Optional[bool]:
        url = self._build_url(coupon)
        if not url:
            logger.error(
                "No api_url configured for site | site_id=%s", self.site.id
            )
            return None
        client = await self._get_or_create_client()
        try:
            # First try calling API directly without login
            logger.info(
                "Calling coupon API | code=%s url=%s (pre-login attempt)",
                coupon.code,
                url,
            )
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/json, text/plain;q=0.8, */*;q=0.5"
                },
                follow_redirects=True,
            )

            def looks_like_password_gate(response: httpx.Response) -> bool:
                try:
                    final_url = str(response.url)
                    if "/password" in final_url:
                        return True
                    if response.status_code in (401, 403):
                        return True
                    ctype = response.headers.get("Content-Type", "")
                    if "text/html" in ctype.lower():
                        text_snippet = (response.text or "")[0:1000].lower()
                        if (
                            "storefront_password" in text_snippet
                            or 'name="password"' in text_snippet
                        ):
                            return True
                    return False
                except Exception:
                    return False

            if looks_like_password_gate(resp):
                # Check if we need to re-login (session might have expired)
                if not await self._verify_session_still_valid(client, url):
                    logger.info(
                        "Session expired, re-logging in | code=%s", coupon.code
                    )
                    self._storefront_logged_in = False

                # Perform login and retry once
                await self._ensure_storefront_login(client, url)
                logger.info(
                    "Retrying coupon API after storefront login | code=%s url=%s",
                    coupon.code,
                    url,
                )

                # Debug: log cookies after login
                logger.debug("Cookies after login: %s", client.cookies)

                resp = await client.get(
                    url,
                    headers={
                        "Accept": "application/json, text/plain;q=0.8, */*;q=0.5"
                    },
                    follow_redirects=True,
                )

            text = resp.text
            data: Optional[dict] = None
            if "application/json" in resp.headers.get("Content-Type", ""):
                try:
                    data = resp.json()
                except Exception:
                    try:
                        data = json.loads(text)
                    except Exception:
                        data = None
            result = self._interpret_boolean_response(text, data)
            # Persist rule JSON if present
            try:
                if isinstance(data, dict) and isinstance(
                    data.get("rule"), dict
                ):
                    coupon.rule = data["rule"]
                    coupon.rule["discount"] = data["discount"]
            except Exception:
                pass
            if result is None:
                if resp.status_code == 200 and result is None:
                    logger.debug(
                        "Coupon API returned 200 but no definitive result | code=%s",
                        coupon.code,
                    )
                else:
                    logger.warning(
                        "Undecidable response | code=%s status=%s body_snippet=%s",
                        coupon.code,
                        resp.status_code,
                        (text[:200] if text else ""),
                    )
            return result
        except httpx.RequestError as e:
            logger.error(
                "Coupon API request error | code=%s url=%s error=%s",
                coupon.code,
                url,
                e,
            )
            return None
        except asyncio.TimeoutError as e:
            logger.error(
                "Coupon API request timed out | code=%s url=%s",
                coupon.code,
                url,
                e,
            )
            return None
        except Exception as e:
            logger.exception(
                "Coupon API unexpected error | code=%s url=%s error=%s",
                coupon.code,
                url,
                e,
            )
            return None

    async def validate(
        self, coupons: List[Coupon]
    ) -> List[Tuple[Coupon, bool]]:
        """Validate coupons via HTTP API.

        For each coupon:
          - True: set status=VALID
          - False: set status=INVALID
          - None: leave status as-is
        Always updates last_checked_at.
        """
        results: List[Tuple[Coupon, bool]] = []
        try:
            for coupon in coupons:
                try:
                    result = await self._check_coupon(coupon)
                    if result is True:
                        coupon.status = CouponStatus.VALID
                    elif result is False:
                        coupon.status = CouponStatus.INVALID
                    coupon.last_checked_at = datetime.now(UTC)
                    results.append((coupon, result is True))
                except Exception as e:
                    logger.exception(
                        "Error validating coupon %s via API: %s",
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
